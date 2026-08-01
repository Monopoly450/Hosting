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
import logging

logger = logging.getLogger("app.services.cloudinit")

# Порог с запасом относительно лимита KubeVirt (2048 байт).
INLINE_LIMIT_BYTES = 1900


def build_stable_netplan_yaml(pod_mac: str, lan_mac: str, static_ip: str = None) -> str:
    """Netplan (отступ 6 пробелов — годится прямо в write_files/content) с
    интерфейсами, матчащимися по MAC, а не по имени в госте.

    pod-nic (сеть кластера/интернет) — всегда DHCP.
    stable-nic (мост br-vms) — статический адрес, если он вычислен для этой
    ВМ; иначе тоже DHCP (для вызовов без static_ip).

    Раньше маркетплейс и деплой из GitHub писали свой netplan с dhcp4 на ВСЕ
    "e*"-интерфейсы вместо этого. Второй (мостовой) интерфейс из-за этого не
    получал статический адрес, а брал DHCP-аренду из пула dnsmasq: адрес
    «плавал» между перезагрузками и мог совпасть с чужой статической ВМ на
    том же мосту. generate_linux_manifest использует эту же функцию, поэтому
    расхождения между обычными ВМ и маркетплейсом/деплоем больше не будет.
    """
    if static_ip:
        stable_block = f"""          stable-nic:
            match:
              macaddress: "{lan_mac}"
            dhcp4: false
            addresses: [{static_ip}/24]"""
    else:
        stable_block = f"""          stable-nic:
            match:
              macaddress: "{lan_mac}"
            dhcp4: true"""
    return f"""      network:
        version: 2
        ethernets:
          pod-nic:
            match:
              macaddress: "{pod_mac}"
            dhcp4: true
            dhcp4-overrides:
              use-routes: true
{stable_block}"""


# KubeVirt узнаёт IP мостового (не pod-) интерфейса ТОЛЬКО через qemu-guest-agent
# — в отличие от pod-сети, адрес которой известен ему и без гостя. Одна
# неудачная попытка apt-get (например, из-за занятого dpkg-лока
# unattended-upgrades сразу после загрузки) навсегда лишала ВМ видимого
# мостового адреса: агент никто не переустанавливал. У обычных ВМ
# (generate_linux_manifest) уже был цикл до 50 попыток — маркетплейс и деплой
# из GitHub писали одну попытку без повтора. Теперь у всех одна и та же команда.
GUEST_AGENT_RETRY_RUNCMD = (
    "  - i=1; while [ $i -le 50 ]; do (apt-get update && apt-get install -y qemu-guest-agent) "
    "&& break || (dnf install -y qemu-guest-agent) && break || (yum install -y qemu-guest-agent) "
    "&& break || sleep 5; i=$((i+1)); done || true\n"
    "  - systemctl enable --now qemu-guest-agent || true"
)


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
        # Заменяем inline-данные ссылкой на Secret.
        # Поле называется именно secretRef: userDataSecretRef в схеме KubeVirt
        # нет, неизвестное поле молча отбрасывается, и валидатор ругается
        # «must have at least one userdatasource set».
        # networkDataSecretRef — это уже про network-data, не про userdata.
        volume["cloudInitNoCloud"] = {"secretRef": {"name": secret_name}}
        moved = True
        logger.info(
            f"cloud-init для ВМ {vm_name} ({len(userdata.encode())} байт) вынесен "
            f"в Secret {secret_name}: inline-лимит KubeVirt — 2048 байт"
        )
    return moved
