"""Вынос большого cloud-init в Secret.

KubeVirt отклоняет манифест, если inline `cloudInitNoCloud.userData` превышает
2048 байт:

    admission webhook denied the request: cloudInitNoCloud userdata exceeds
    2048 byte limit. Should use UserDataSecretRef for larger data.

Cloud-init маркетплейса содержит внутри себя docker-compose.yml и .env, поэтому
в лимит не влезает — без этого выноса приложения с базой данных (WordPress,
Nextcloud) вообще не создавались. Деплой из репозитория с длинным набором шагов
упирался в то же ограничение.

Небольшой userData оставляем inline: так меньше сущностей в кластере и не
ломается поведение обычных ВМ.
"""
import json
import logging

logger = logging.getLogger("app.services.cloudinit")

# Порог с запасом относительно лимита KubeVirt (2048 байт).
INLINE_LIMIT_BYTES = 1900


def build_network_data(pod_mac: str, lan_mac: str, static_ip: str = None) -> str:
    """network-config v2 для поля cloudInitNoCloud.networkData.

    pod-nic (сеть кластера/интернет) — всегда DHCP.
    stable-nic (мост br-vms) — статический адрес, если он вычислен для этой
    ВМ; иначе тоже DHCP. Интерфейсы матчатся по MAC, а не по имени: имена
    (eth0/ens3/enp1s0) зависят от дистрибутива и порядка устройств.

    Раньше этот же YAML писался файлом в /etc/netplan/99-dhcp.yaml через
    write_files. Netplan — инструмент Ubuntu, его нет ни в RHEL-семействе
    (CentOS/Rocky/Alma/Fedora — там NetworkManager), ни в openSUSE (wicked),
    ни в Arch, ни в Alpine, ни даже в облачных образах Debian. На восьми из
    десяти поддерживаемых Linux-систем файл просто ложился на диск, и его
    никто не читал: мостовой интерфейс оставался ненастроенным, статический
    адрес не применялся — ровно то, что выглядит как «сетевой адаптер не
    работает на этой ОС».

    networkData обрабатывает сам cloud-init и рендерит в то, чем система
    реально пользуется: netplan в Ubuntu, sysconfig/NetworkManager в
    RHEL-семействе, /etc/network/interfaces в Debian и Alpine,
    systemd-networkd в Arch. Формат v2 — тот же самый, что у netplan,
    поэтому содержимое не меняется, меняется способ доставки.
    """
    if static_ip:
        stable_block = f"""  stable-nic:
    match:
      macaddress: "{lan_mac}"
    dhcp4: false
    addresses: [{static_ip}/24]"""
    else:
        stable_block = f"""  stable-nic:
    match:
      macaddress: "{lan_mac}"
    dhcp4: true"""
    return f"""version: 2
ethernets:
  pod-nic:
    match:
      macaddress: "{pod_mac}"
    dhcp4: true
    dhcp4-overrides:
      use-routes: true
{stable_block}
"""


# KubeVirt узнаёт IP мостового (не pod-) интерфейса ТОЛЬКО через qemu-guest-agent
# — в отличие от pod-сети, адрес которой известен ему и без гостя. Одна
# неудачная попытка apt-get (например, из-за занятого dpkg-лока
# unattended-upgrades сразу после загрузки) навсегда лишала ВМ видимого
# мостового адреса: агент никто не переустанавливал. У обычных ВМ
# (generate_linux_manifest) уже был цикл до 50 попыток — маркетплейс и деплой
# из GitHub писали одну попытку без повтора. Теперь у всех одна и та же команда.
#
# Перебираем ВСЕ менеджеры пакетов, а не только apt/dnf/yum: без zypper
# (openSUSE), pacman (Arch) и apk (Alpine) агент на этих системах не ставился
# вообще, и панель никогда не узнавала адрес мостового интерфейса такой ВМ.
# В Alpine нет systemd — там служба поднимается через OpenRC.
def guest_agent_runcmd(os_type: str = "ubuntu") -> str:
    """Установка qemu-guest-agent с повтором, начиная с «родного» для системы
    менеджера пакетов.

    Порядок попыток зависит от ОС не ради красоты: с жёстко зашитым apt-get
    первым каждый лог cloud-init на не-Debian системе начинался со строки
    «apt-get: command not found». Работало за счёт запасных вариантов, но при
    разборе проблем это сбивает с толку в первую очередь.
    """
    from app.services.os_profiles import install_package_cmd_chain

    chain = install_package_cmd_chain(os_type, "qemu-guest-agent")
    return (
        f"  - i=1; while [ $i -le 50 ]; do {chain} || "
        "sleep 5; i=$((i+1)); done || true\n"
        "  - systemctl enable --now qemu-guest-agent 2>/dev/null || "
        "(rc-update add qemu-guest-agent default && rc-service qemu-guest-agent start) 2>/dev/null || true"
    )


# Обратная совместимость для маркетплейса и деплоя из GitHub: они всегда
# создают Ubuntu-машины, поэтому им достаточно варианта по умолчанию.
GUEST_AGENT_RETRY_RUNCMD = guest_agent_runcmd("ubuntu")


# Ожидание сети перед шагами, которым нужен интернет. Ограничено по времени —
# это принципиально: раньше здесь стоял `while ! ping ...; do sleep 2; done`
# БЕЗ верхней границы, и всё, что идёт после (установка guest-agent и команды
# шаблона окружения), не выполнялось никогда, если ICMP наружу закрыт. А в
# университетских и корпоративных сетях исходящий ICMP к 8.8.8.8 блокируют
# сплошь и рядом, при полностью рабочем HTTP.
#
# Из-за этого расхождение выглядело как «шаблоны работают только на Ubuntu»:
# пакеты ставит модуль packages, он отрабатывает ДО runcmd и от зависания не
# страдает, а вот запуск служб живёт в runcmd. В Debian и Ubuntu политика
# пакетов требует стартовать демон прямо при установке — сайт поднимался сам,
# даже когда runcmd висел. В RHEL, SUSE, Arch и Alpine службы после установки
# не стартуют, их включает только `systemctl enable --now` из runcmd — то есть
# ровно то, до чего исполнение не доходило. Плюс на ЛЮБОЙ системе не ставился
# qemu-guest-agent, поэтому панель не узнавала адрес ВМ на мосту и проброс
# портов вёл в никуда — отсюда и «сайты не работают».
#
# 60 попыток по 2 секунды — не больше двух минут, после чего продолжаем в
# любом случае: даже без интернета осмысленнее выполнить остальные шаги, чем
# зависнуть навсегда.
WAIT_NETWORK_RUNCMD = (
    "  - i=1; while [ $i -le 60 ] && ! ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; "
    "do sleep 2; i=$((i+1)); done || true"
)


# Запуск docker compose с повторами. Одной попытки мало: образы приложений
# маркетплейса весят под гигабайт (Nextcloud тянет ещё и PostgreSQL), и любой
# срыв скачивания — недоступное на минуту зеркало, не до конца поднявшийся
# демон docker — оставлял приложение ненастроенным НАВСЕГДА: ошибка гасилась
# через `|| true`, а повторить попытку было некому. Снаружи это выглядит как
# «ВМ запущена, а сайт не открывается» — без единого следа в панели.
#
# Ждём и готовности самого демона: systemctl enable --now docker возвращает
# управление раньше, чем dockerd начинает принимать команды.
COMPOSE_UP_RUNCMD = (
    "  - i=1; while [ $i -le 30 ] && ! docker info >/dev/null 2>&1; "
    "do sleep 2; i=$((i+1)); done || true\n"
    "  - i=1; while [ $i -le 10 ]; do cd /opt/app && "
    "(docker compose up -d || docker-compose up -d) && break || sleep 15; "
    "i=$((i+1)); done || true"
)


def yaml_runcmd_lines(commands, indent: str = "  ") -> str:
    """Рендерит команды как элементы YAML-списка runcmd, экранируя каждую.

    Подставлять команду в YAML как есть нельзя. Реальный случай: команда
    записи индексной страницы содержала «своим сайтом: /var/www/html», и
    YAML разобрал двоеточие с пробелом как разделитель ключа и значения —
    элемент runcmd стал СЛОВАРЁМ вместо строки. Документ при этом остаётся
    формально валидным, ошибки разбора нет, а cloud-init на таком элементе
    спотыкается, и весь runcmd дальше не выполняется. Симптом: шаблоны не
    работают вообще ни на одной системе, хотя в логе ничего внятного нет.

    json.dumps даёт валидный YAML-скаляр в двойных кавычках (YAML —
    надмножество JSON), с корректным экранированием кавычек, обратных слешей
    и управляющих символов. ensure_ascii=False оставляет кириллицу читаемой.
    """
    out = []
    for cmd in commands:
        if not cmd:
            continue
        out.append(f"{indent}- {json.dumps(cmd, ensure_ascii=False)}")
    return "\n".join(out)


def _userdata_volumes(manifest: dict):
    """Тома с inline cloud-init внутри манифеста ВМ."""
    spec = (manifest or {}).get("spec", {}).get("template", {}).get("spec", {})
    for volume in spec.get("volumes", []) or []:
        cloud_init = volume.get("cloudInitNoCloud")
        if isinstance(cloud_init, dict) and cloud_init.get("userData"):
            yield volume, cloud_init


def needs_secret(userdata: str) -> bool:
    return len(userdata.encode("utf-8")) > INLINE_LIMIT_BYTES


def externalize_cloudinit(k8s, manifest: dict, vm_name: str, namespace: str = "default") -> bool:
    """Переносит слишком большой cloud-init в Secret и правит манифест.

    Возвращает True, если перенос понадобился. Вызывать ДО создания ВМ:
    манифест должен уже ссылаться на существующий Secret.
    """
    moved = False
    for volume, cloud_init in list(_userdata_volumes(manifest)):
        userdata = cloud_init["userData"]
        if not needs_secret(userdata):
            continue
        secret_name = k8s.create_cloudinit_secret(vm_name, userdata, namespace)
        # Заменяем inline userData ссылкой на Secret, но НЕ весь cloudInitNoCloud:
        # networkData лежит в том же объекте (см. build_network_data), и старый
        # код затирал его вместе с userData — `volume["cloudInitNoCloud"] = {...}`
        # выбрасывал все прочие ключи. Сеть терялась молча у любого шаблона
        # тяжелее ~1900 байт (WordPress, LAMP с SSH-ключом, весь маркетплейс —
        # там всегда docker-compose+.env), а Ubuntu просто маскировала пропажу
        # собственным DHCP-фолбэком в cloud-init, которого нет у других систем:
        # отсюда и «работает только на Ubuntu» независимо от выбранного шаблона.
        #
        # Поле называется именно secretRef: userDataSecretRef в схеме KubeVirt
        # нет, неизвестное поле молча отбрасывается, и валидатор ругается
        # «must have at least one userdatasource set».
        # networkDataSecretRef — это уже про network-data, не про userdata.
        cloud_init.pop("userData", None)
        cloud_init.pop("userDataBase64", None)
        cloud_init["secretRef"] = {"name": secret_name}
        moved = True
        logger.info(
            f"cloud-init для ВМ {vm_name} ({len(userdata.encode())} байт) вынесен "
            f"в Secret {secret_name}: inline-лимит KubeVirt — 2048 байт"
        )
    return moved
