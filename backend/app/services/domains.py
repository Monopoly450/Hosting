"""Свои домены с автоматическим TLS.

Приложения живут в ВМ за пробросом портов, поэтому вместо k8s-Ingress
используем Caddy как реверс-прокси на хосте: он сам получает и продлевает
сертификаты Let's Encrypt (ACME) для каждого домена.

Caddy запускается с сетью хоста, поэтому доступен на 80/443 и одновременно
видит IP виртуалок на мосту. Конфиг кладём внутрь контейнера через docker API
(put_archive) — не завязываемся на путях хоста.
"""
import io
import logging
import os
import re
import socket
import tarfile
from typing import Optional

logger = logging.getLogger("app.services.domains")

CADDY_CONTAINER = "aegis-caddy"
CADDY_VOLUME = "aegis-caddy-data"      # тут Caddy хранит сертификаты
# Не голый caddy:2: DNS-провайдеры (см. panel_entry) — Go-плагины, которые
# линкуются в бинарник статически, поэтому образ собирается локально через
# xcaddy (aegis-caddy/Dockerfile), а не тянется из реестра.
CADDY_IMAGE = "aegis-caddy:local"
CADDY_BUILD_CONTEXT = "/app/repo/aegis-caddy"
CADDYFILE_PATH = "/etc/caddy/Caddyfile"

# Боевой каталог Let's Encrypt. Задаётся явно, чтобы Caddy не уходил на
# staging после неудачных попыток — см. пояснение в build_caddyfile.
LETSENCRYPT_PROD_CA = "https://acme-v02.api.letsencrypt.org/directory"

# Метка домена: буквы/цифры/дефис, до 63 символов; минимум два уровня.
DOMAIN_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


def host_ip() -> str:
    from app.core.netutils import detect_host_ip
    return detect_host_ip()


def acme_email() -> str:
    return os.getenv("ACME_EMAIL", "")


# Порт из frontend/nginx.conf: plain HTTP, только на loopback — сюда
# проксирует локальный Caddy, когда обслуживает домен самой панели.
PANEL_UPSTREAM = "127.0.0.1:8081"

# Оба сервиса из docker-compose.yml уже отдают себя обычным HTTP на loopback
# (webmail: контейнер roundcube слушает 80, наружу — 127.0.0.1:8082; minio:
# консоль на ":9001" без своего TLS) — отдельный plain-листенер, как для
# панели, им не нужен.
MAIL_UPSTREAM = "127.0.0.1:8082"
STORAGE_UPSTREAM = "127.0.0.1:9001"
# Веб-консоль RabbitMQ. Как и остальные служебные порты, слушает только
# 127.0.0.1 (см. docker-compose.yml) — до неё либо SSH-туннель, либо этот
# домен через Caddy. Учётные данные у неё свои: RABBITMQ_USER/RABBITMQ_PASS.
RABBITMQ_UPSTREAM = "127.0.0.1:15672"

# Служебные сервисы хоста, которым можно дать свой домен.
#
# Таблица, а не набор веток: раньше каждый новый сервис требовал править и
# system_domain_entries, и /api/domains/status, и add-domain.sh — и они
# разъезжались. Теперь достаточно строки здесь.
#
# Сюда попадает только то, что отдаёт HTTP: Caddy — реверс-прокси для HTTP, и
# СУБД через него не проксируются. PostgreSQL и MariaDB общаются по своему
# бинарному протоколу поверх TCP, поэтому домена у них быть не может — к ним
# подключаются по адресу и порту (см. «хаб подключения» у баз в панели).
SYSTEM_SERVICES = (
    # (env-переменная, upstream, человеческое имя)
    ("PANEL_DOMAIN", PANEL_UPSTREAM, "панель управления"),
    ("MAIL_DOMAIN", MAIL_UPSTREAM, "вебмейл (Roundcube)"),
    ("STORAGE_DOMAIN", STORAGE_UPSTREAM, "консоль хранилища (MinIO)"),
    ("RABBITMQ_DOMAIN", RABBITMQ_UPSTREAM, "консоль очереди (RabbitMQ)"),
)


def panel_domain() -> str:
    return os.getenv("PANEL_DOMAIN", "")


def mail_domain() -> str:
    return os.getenv("MAIL_DOMAIN", "")


def storage_domain() -> str:
    return os.getenv("STORAGE_DOMAIN", "")


def rabbitmq_domain() -> str:
    return os.getenv("RABBITMQ_DOMAIN", "")


def system_domains() -> dict:
    """{env-переменная в нижнем регистре: домен} — для /api/domains/status."""
    return {env.lower(): os.getenv(env, "") for env, _, _ in SYSTEM_SERVICES}


def timeweb_dns_token() -> str:
    return os.getenv("TIMEWEB_DNS_API_TOKEN", "")


def cloudflare_dns_token() -> str:
    return os.getenv("CLOUDFLARE_DNS_API_TOKEN", "")


# Имя провайдера здесь — это имя плагина Caddy (caddy-dns/<name>), поэтому
# оно же попадает в директиву `dns <name> <token>` Caddyfile. Плагины должны
# быть собраны в образ: см. aegis-caddy/Dockerfile.
DNS_PROVIDERS = (
    ("cloudflare", cloudflare_dns_token),
    ("timeweb", timeweb_dns_token),
)

DEFAULT_DNS_PROVIDER = "timeweb"


def dns_provider() -> tuple:
    """(имя провайдера, токен) из .env или ("", "").

    Провайдер не один намеренно: сервер за NAT — обычное дело не только у
    Timeweb, а DNS-01 работает у любого провайдера с API. Порядок фиксирован,
    чтобы при двух заданных токенах поведение не зависело от порядка словаря.
    """
    for name, getter in DNS_PROVIDERS:
        token = getter()
        if token:
            return name, token
    return "", ""


def dns_token() -> str:
    """Токен активного провайдера — без разницы, какого именно."""
    return dns_provider()[1]


def _system_entry(domain: str, upstream: str, token: str, provider: str = "") -> Optional[dict]:
    if not domain or not token:
        return None
    entry = {"domain": domain, "upstream": upstream, "dns_token": token}
    if provider and provider != DEFAULT_DNS_PROVIDER:
        entry["dns_provider"] = provider
    return entry


def panel_entry() -> Optional[dict]:
    """Синтетическая запись для домена самой панели (не клиентской ВМ).

    Обычный ACME (HTTP-01) для неё не пройдёт: A-запись такого домена
    нарочно указывает на приватный IP (см. is_private_host_ip), а Let's
    Encrypt при HTTP-01 стучится на порт 80 ИЗВНЕ. Вместо этого просим Caddy
    подтвердить владение через DNS-01 у Timeweb — тогда он сам создаёт
    временную TXT-запись через API, и подключение к серверу снаружи для
    выпуска сертификата не требуется вовсе.

    None, если панель не настроена как отдельный домен (нет PANEL_DOMAIN
    или токена DNS-провайдера) — тогда всё ведёт себя как раньше.
    """
    provider, token = dns_provider()
    return _system_entry(panel_domain(), PANEL_UPSTREAM, token, provider)


def system_domain_entries() -> list:
    """Домены служебных сервисов хоста — не только панели.

    Почта, консоль MinIO и консоль RabbitMQ живут на том же самом хосте с тем
    же приватным IP, что и панель — упираются в ровно то же ограничение
    HTTP-01/TLS-ALPN-01 (см. panel_entry). Каждый сервис — своя отдельная,
    необязательная переменная окружения; ничего не настроено — ничего не
    добавляется, поведение не меняется.

    Список сервисов — в SYSTEM_SERVICES, добавление нового не требует правок
    здесь.
    """
    provider, token = dns_provider()
    entries = []
    for env, upstream, _label in SYSTEM_SERVICES:
        entry = _system_entry(os.getenv(env, ""), upstream, token, provider)
        if entry:
            entries.append(entry)
    return entries


def default_target_port(vm) -> int:
    """Порт внутри ВМ, на который логично направить домен.

    Шаблон уже знает, где слушает его сервис: Grafana — 3000, Portainer —
    9000, всё остальное — обычный веб-сервер на 80. Спрашивать это у
    пользователя было лишним: он должен был помнить порт наизусть, а ошибка
    всплывала только через несколько минут — доменом, который никуда не ведёт.
    """
    from app.services.os_profiles import template_port

    return template_port(getattr(vm, "cloud_init_template", None)) or 80


def is_valid_domain(domain: str) -> bool:
    if not domain or len(domain) > 253:
        return False
    return bool(DOMAIN_RE.match(domain))


# ----------------------------- Конфиг Caddy ---------------------------------

def build_caddyfile(entries: list, email: str = "") -> str:
    """Собирает Caddyfile из списка {domain, upstream}.

    Caddy сам выпускает и продлевает сертификат для каждого блока сайта.
    """
    lines = []
    if email:
        lines += ["{", f"\temail {email}", "}", ""]

    for e in sorted(entries, key=lambda x: x["domain"]):
        lines.append(f"{e['domain']} {{")
        if e.get("dns_token"):
            # DNS-01 вместо обычного HTTP-01 — см. panel_entry().
            #
            # По умолчанию Caddy проверяет распространение записи, спрашивая
            # НАПРЯМУЮ авторитетные NS домена (в обход резолверов), а
            # propagation_delay=0 — идёт проверять сразу после создания
            # записи. На живом сервере это подводило несколько раз подряд:
            # прямой запрос к NS Timeweb по TCP:53 подвисал на ~40с и падал
            # по таймауту (похоже, исходящий TCP:53 наружу режет файрвол
            # хостера); без задержки Let's Encrypt иногда успевал спросить
            # раньше, чем новое значение TXT (токен каждой ACME-попытки
            # новый) реально разошлось; а когда одновременно заводили сразу
            # несколько доменов (панель + почта + хранилище), NS Timeweb не
            # укладывался и в дефолтный propagation_timeout=2m — Cloudflare
            # уже видел свежую запись, Google ещё нет. Резолверы ниже —
            # обычные публичные, они точно доступны с любого сервера;
            # задержка даёт записи время долистать TTL=600 до края; таймаут
            # увеличен с запасом под медленный NS.
            #
            # issuer задан ЯВНО и ровно один — это и есть защита от главной
            # оставшейся поломки. По умолчанию Caddy держит список УЦ (боевой
            # Let's Encrypt, ZeroSSL) и после нескольких неудач сам уходит на
            # staging. Дальше он начинает чередовать попытки: staging и боевой
            # выпуск идут по одному и тому же имени _acme-challenge.<домен>,
            # каждый пишет туда свой токен и затирает чужой. Итог в логе —
            # «Incorrect TXT record found»: проверяющий видит токен соседней
            # попытки. Плюс сертификат от staging браузеры не считают
            # доверенным, а панель при этом показывает домен активным.
            # С одним явным issuer метаться некуда.
            lines.append("\ttls {")
            lines.append(f"\t\tissuer acme {LETSENCRYPT_PROD_CA} {{")
            if email:
                # Глобальный `email` относится к УЦ по умолчанию; у явного
                # issuer свой, иначе аккаунт ACME будет без контакта.
                lines.append(f"\t\t\temail {email}")
            lines.append(f"\t\t\tdns {e.get('dns_provider') or DEFAULT_DNS_PROVIDER} {e['dns_token']}")
            lines.append("\t\t\tresolvers 1.1.1.1 8.8.8.8")
            lines.append("\t\t\tpropagation_delay 30s")
            lines.append("\t\t\tpropagation_timeout 5m")
            lines.append("\t\t}")
            lines.append("\t}")
        lines.append(f"\treverse_proxy {e['upstream']}")
        lines.append("}")
        lines.append("")

    if not entries:
        # Пустой конфиг невалиден — оставляем заглушку, чтобы Caddy стартовал.
        #
        # Порт НЕ 8080: Caddy работает в network_mode host (нужен доступ к
        # 80/443 хоста и к IP виртуалок напрямую), а на 8080 уже слушает сама
        # панель (frontend/nginx.conf). Пока не настроен ни один домен, кто из
        # них запустится раньше — тот и займёт порт; второй не забиндится и
        # тихо упадёт. Реальный симптом на живом сервере: вместо панели
        # браузер показывал "Aegis: домены не настроены" — заглушку Caddy,
        # выигравшего гонку за порт панели. Держим порт этой заглушки заведомо
        # не пересекающимся ни с чем из docker-compose.yml.
        lines.append("# нет активных доменов")
        lines.append(":18080 {")
        lines.append("\trespond \"Aegis: домены не настроены\" 200")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


CHALLENGE_PREFIX = "_aegis-challenge"


def generate_verification_token() -> str:
    import secrets
    return "aegis-verify-" + secrets.token_hex(16)


def challenge_record_name(domain: str) -> str:
    return f"{CHALLENGE_PREFIX}.{domain}"


def check_ownership(domain: str, token: str) -> tuple:
    """Проверяет TXT-запись _aegis-challenge.<домен> с нашим токеном.

    Без этого любой пользователь панели мог бы добавить чужой домен, который
    и так указывает на этот сервер (например, домен самой панели), и увести
    его трафик на свою ВМ. Поэтому владение подтверждается отдельно от A-записи.
    """
    if not token:
        return False, "нет токена подтверждения"
    name = challenge_record_name(domain)
    try:
        import dns.resolver
    except ImportError:
        return False, "на сервере не установлен dnspython"

    # Системный резолвер (обычно локальный стаб systemd-resolved) сдаётся по
    # своему таймауту раньше, чем успевает дождаться ответа от медленных
    # авторитетных NS — на живом сервере тот же NS Timeweb (139.45.249.139)
    # отвечал на некоторые запросы 3+ секунды (см. build_caddyfile/
    # propagation_delay). Публичные резолверы обычно терпеливее и не путают
    # "сервер не ответил вовремя" с NXDOMAIN.
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = ["1.1.1.1", "8.8.8.8"]
    resolver.timeout = 5
    resolver.lifetime = 10
    try:
        answers = resolver.resolve(name, "TXT")
    except Exception as e:
        return False, f"TXT-запись {name} не найдена: {e}"

    for rdata in answers:
        for chunk in getattr(rdata, "strings", []):
            value = chunk.decode(errors="ignore") if isinstance(chunk, bytes) else str(chunk)
            if value.strip() == token:
                return True, "владение подтверждено"
    return False, f"в TXT-записи {name} нет нужного значения"


def check_dns(domain: str, expected_ip: str = None) -> tuple:
    """Проверяет, что A-запись домена указывает на наш хост.
    Возвращает (ok, resolved_ip_or_error)."""
    expected = expected_ip or host_ip()

    # host_for_links() (см. netutils, вызывающая сторона в api/domains.py)
    # отдаёт не всегда IP — если панель открыта по доменному имени (например,
    # по PANEL_DOMAIN, который сам указывает на приватный IP), expected_ip
    # приходит сюда как это самое имя. Сравнение строки-домена со строкой-IP
    # другого домена не совпадёт никогда, даже если оба домена ведут на один
    # и тот же сервер — резолвим такое имя в IP перед сравнением.
    import ipaddress
    try:
        ipaddress.ip_address(expected)
    except ValueError:
        try:
            expected = socket.gethostbyname(expected)
        except OSError as e:
            return False, f"не удалось определить IP для {expected_ip}: {e}"

    try:
        resolved = socket.gethostbyname(domain)
    except Exception as e:
        return False, f"DNS не резолвится: {e}"
    if resolved != expected:
        return False, f"A-запись указывает на {resolved}, ожидается {expected}"
    return True, resolved


# --------------------------- Разрешение целей -------------------------------

def resolve_upstream(db, k8s, dom):
    """Возвращает ('ip:port', None) для домена или (None, причина)."""
    from app.models.models import AppDeployment, VMTask

    if dom.target_type == "deployment":
        dep = db.query(AppDeployment).filter(AppDeployment.id == dom.target_id).first()
        if not dep:
            return None, "деплой не найден"
        vm = db.query(VMTask).filter(VMTask.id == dep.vm_id).first() if dep.vm_id else None
    else:
        vm = db.query(VMTask).filter(VMTask.id == dom.target_id).first()

    if not vm:
        return None, "ВМ не найдена"

    ip = None
    try:
        from app.core.netutils import pick_external_ip
        ips = (k8s.get_vm(vm.name) or {}).get("ips") or []
        ip = pick_external_ip(ips) if ips else None
    except Exception as e:
        logger.warning(f"resolve_upstream {dom.domain}: {e}")
    ip = ip or vm.static_ip  # статический IP как надёжный запасной вариант
    if not ip:
        return None, "у ВМ ещё нет IP"
    return f"{ip}:{dom.target_port}", None


def build_entries(db, k8s) -> list:
    """Список {domain, upstream} для доменов, готовых к проксированию.

    Требуется И подтверждённое владение (TXT), И корректная A-запись — иначе
    домен вообще не попадёт в конфиг прокси.
    """
    from app.models.models import Domain

    entries = list(system_domain_entries())

    # Тот же приватный IP, что мешает панели (см. panel_entry), мешает и
    # клиентским доменам: HTTP-01/TLS-ALPN-01 требуют, чтобы Let's Encrypt
    # мог достучаться до хоста извне, а с приватным IP это невозможно в
    # принципе — живой пример: "no valid A records found for <домен>"
    # (Let's Encrypt просто не считает приватный адрес валидным). Caddy
    # сидит на одном-единственном хосте (network_mode host), так что для
    # всех доменов это одно и то же да/нет — проверяем раз, а не на каждый
    # домен отдельно.
    provider, token = dns_provider() if is_private_host_ip() else ("", "")

    ready = db.query(Domain).filter(
        Domain.dns_ok == True, Domain.ownership_ok == True  # noqa: E712
    ).all()
    for dom in ready:
        upstream, err = resolve_upstream(db, k8s, dom)
        if upstream:
            entry = {"domain": dom.domain, "upstream": upstream}
            if token:
                entry["dns_token"] = token
                if provider != DEFAULT_DNS_PROVIDER:
                    entry["dns_provider"] = provider
            entries.append(entry)
    return entries


# --------------------------- Управление Caddy -------------------------------

def is_private_host_ip(ip: str = None) -> bool:
    """True, если адрес хоста не виден из интернета.

    Let's Encrypt проверяет домен, обращаясь к порту 80 ИЗВНЕ. Если A-запись
    указывает на адрес из приватного диапазона (192.168.x, 10.x, 172.16–31.x),
    проверка не пройдёт никогда, а неудачные попытки расходуют лимиты ACME.
    Поэтому предупреждаем до того, как пользователь начнёт править DNS.
    """
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip or host_ip())
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def caddy_status(docker_client, host: str = "") -> dict:
    """host — адрес, по которому открыта панель (см. netutils.host_for_links).

    Раньше здесь всегда стоял detect_host_ip(), а он в первую очередь читает
    AEGIS_HOST_IP. Если переменную однажды задали, подсказка «A @ → ...»
    показывала её вместо фактического адреса сервера, даже когда панель
    открыта по совсем другому адресу.
    """
    current_ip = host or host_ip()
    info = {
        "docker": False,
        "running": False,
        "host_ip": current_ip,
        "host_ip_is_private": is_private_host_ip(current_ip),
    }
    if not docker_client or not docker_client.is_available():
        return info
    info["docker"] = True
    try:
        c = docker_client.client.containers.get(CADDY_CONTAINER)
        info["running"] = (c.status == "running")
    except Exception:
        info["running"] = False
    return info


def _caddy_failure_reason(c) -> str:
    """Последние строки лога контейнера — чтобы причина падения была видна.

    Вотчдог умеет пересоздать зацикленный Caddy, но раньше писал в лог только
    сам факт: «зациклен на перезапуске». Настоящая причина (обычно «address
    already in use» — порт 80 или 443 занят чем-то на хосте) оставалась
    только внутри контейнера, и добраться до неё можно было лишь вручную
    через docker logs. Теперь она попадает в лог воркера сразу.
    """
    try:
        raw = c.logs(tail=15, stdout=True, stderr=True)
        text = raw.decode("utf-8", errors="ignore").strip() if isinstance(raw, bytes) else str(raw).strip()
        return text or "(лог контейнера пуст)"
    except Exception as e:
        return f"(не удалось прочитать лог контейнера: {e})"


def _caddyfile_tar(content: str) -> io.BytesIO:
    """Упаковывает Caddyfile в tar для put_archive."""
    data = content.encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="Caddyfile")
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


# Сколько раз Docker должен успеть перезапустить контейнер, прежде чем мы
# считаем его зациклившимся, а не просто «стартует чуть дольше обычного».
CADDY_CRASH_LOOP_THRESHOLD = 3


def _ensure_caddy_image(cli):
    """Гарантирует наличие образа с плагином caddy-dns/timeweb.

    В отличие от остальных образов (см. docker_client.ensure_image) этот
    нельзя просто скачать: DNS-провайдеры Caddy — Go-модули, линкуемые в
    бинарник статически на этапе сборки (aegis-caddy/Dockerfile), готового
    образа с нужным плагином в публичных реестрах нет.
    """
    from docker.errors import ImageNotFound
    try:
        cli.images.get(CADDY_IMAGE)
        return False
    except ImageNotFound:
        logger.info(f"Собираю образ {CADDY_IMAGE} с плагином caddy-dns/timeweb (первый раз — пара минут)...")
        cli.images.build(path=CADDY_BUILD_CONTEXT, tag=CADDY_IMAGE, rm=True)
        logger.info(f"Образ {CADDY_IMAGE} собран.")
        return True


def _create_caddy(cli, caddyfile: str):
    """Создаёт и запускает Caddy с нуля — общий путь и для первого запуска,
    и для восстановления после зацикленного рестарта (см. ensure_caddy)."""
    _ensure_caddy_image(cli)

    c = cli.containers.create(
        CADDY_IMAGE,
        name=CADDY_CONTAINER,
        detach=True,
        network_mode="host",           # 80/443 хоста + доступ к IP виртуалок
        restart_policy={"Name": "always"},
        volumes={CADDY_VOLUME: {"bind": "/data", "mode": "rw"}},
        command=f"caddy run --config {CADDYFILE_PATH} --adapter caddyfile",
    )
    c.put_archive(os.path.dirname(CADDYFILE_PATH), _caddyfile_tar(caddyfile))
    c.start()
    return c


def _caddy_crash_looping(c) -> bool:
    """Дешёвая проверка состояния уже полученного контейнера (без docker exec) —
    годится для частого опроса вотчдогом, в отличие от полной ensure_caddy."""
    c.reload()
    restart_count = c.attrs.get("RestartCount", 0)
    return c.status == "restarting" or restart_count >= CADDY_CRASH_LOOP_THRESHOLD


# Состояния, из которых контейнер сам уже не выйдет: restart_policy=always
# не действует на контейнер, остановленный явно (docker stop) — он так и
# останется exited, сколько ни жди.
CADDY_STOPPED_STATES = ("exited", "created", "dead", "paused")


def _caddy_state(c) -> Optional[str]:
    """Что не так с контейнером: "crash-loop", "stopped" или None (всё в порядке).

    Различать важно, потому что лечится это по-разному: зацикленный надо
    сносить и создавать заново, а просто остановленный — всего лишь
    запустить. Раньше вотчдог знал только про зацикленный, и Caddy,
    оказавшийся в exited (например, после docker stop или перезапуска демона
    Docker), не поднимался уже никогда: доменов нет — значит, ensure_caddy
    никто не вызовет, а вотчдог такое состояние не считал проблемой.
    """
    if _caddy_crash_looping(c):
        return "crash-loop"
    if c.status in CADDY_STOPPED_STATES:
        return "stopped"
    return None


def ensure_caddy(docker_client, caddyfile: str):
    """Создаёт (если нужно) и запускает Caddy с актуальным конфигом.

    Обнаруженный на живом сервере случай: контейнер не мог занять порт (тот
    же :8080, что и у панели — см. build_caddyfile) и с restart_policy=always
    Docker перезапускал его непрерывно. put_archive/start/reload из старой
    версии этой функции контейнеру в таком состоянии не помогали — файл
    конфига переписывался, но падающий процесс продолжал падать со старым
    закешированным состоянием, и панель оставалась недоступна, пока кто-то не
    удалял контейнер вручную. Теперь зацикленный рестарт распознаётся сам
    (см. _caddy_crash_looping) и лечится единственным надёжным способом —
    снести контейнер и создать заново, а не пытаться его оживить.
    """
    import docker.errors
    cli = docker_client.client
    try:
        c = cli.containers.get(CADDY_CONTAINER)
    except docker.errors.NotFound:
        _create_caddy(cli, caddyfile)
        return {"status": "created"}

    if _caddy_crash_looping(c):
        logger.warning(
            f"{CADDY_CONTAINER} зациклен на перезапуске (status={c.status}, "
            f"RestartCount={c.attrs.get('RestartCount', 0)}) — пересоздаю вместо попытки оживить.\n"
            f"Последние строки его лога:\n{_caddy_failure_reason(c)}"
        )
        c.remove(force=True)
        _create_caddy(cli, caddyfile)
        return {"status": "recreated_after_crash_loop"}

    c.put_archive(os.path.dirname(CADDYFILE_PATH), _caddyfile_tar(caddyfile))
    if c.status != "running":
        c.start()
        return {"status": "started"}
    return reload_caddy(docker_client)


def reconcile_caddy(db, k8s, docker_client) -> bool:
    """Вотчдог для периодического опроса: чинит зацикленный Caddy сам, без
    участия пользователя. Без настроенных доменов ничего в панели не вызывает
    ensure_caddy() автоматически — единственным способом восстановления был
    ручной `docker rm` на самом сервере. Возвращает True, если пересоздавали.

    Дешёвая проверка _caddy_crash_looping() выполняется на каждый тик;
    дорогая пересборка конфига (запрос к БД и K8s под build_entries) — только
    когда контейнер реально найден зацикленным.
    """
    import docker.errors
    try:
        c = docker_client.client.containers.get(CADDY_CONTAINER)
    except docker.errors.NotFound:
        # Раньше «нечего лечить» было верно всегда: без доменов в БД никто
        # не вызывал ensure_caddy(), а значит, и создавать нечего. Теперь
        # panel_entry() может дать непустой список entries ещё до того, как
        # в БД появится хоть один клиентский домен — тогда именно вотчдог
        # (единственное, что тикает само по себе, без участия пользователя)
        # должен поднять Caddy впервые.
        entries = build_entries(db, k8s)
        if not entries:
            return False  # ещё не создавался и разворачивать нечего
        _create_caddy(docker_client.client, build_caddyfile(entries, acme_email()))
        return True
    except Exception as e:
        logger.error(f"reconcile_caddy: не удалось получить контейнер {CADDY_CONTAINER}: {e}")
        return False

    state = _caddy_state(c)
    if state is None:
        return False

    # Причина — в лог сразу, до пересоздания: после него контейнер будет уже
    # новый, и прежние строки о падении пропадут вместе со старым.
    logger.warning(
        f"{CADDY_CONTAINER}: состояние «{state}». Последние строки его лога:\n"
        f"{_caddy_failure_reason(c)}"
    )

    if state == "stopped":
        # Останавливать Caddy незачем ни одному сценарию панели, поэтому
        # exited — это всегда сбой. Пробуем просто запустить: конфиг в
        # контейнере уже лежит, пересобирать его (запрос в БД и K8s) ради
        # этого не нужно.
        try:
            c.start()
            logger.warning(f"{CADDY_CONTAINER} был остановлен ({c.status}) — запущен вотчдогом.")
            return True
        except Exception as e:
            # Не запускается — значит, дело не в том, что его просто
            # остановили (так бывает при занятом порте). Лечим тем же
            # надёжным способом, что и зацикленный: сносим и создаём заново.
            # Через ensure_caddy идти нельзя — она попыталась бы стартовать
            # ровно этот же контейнер и упала бы снова.
            logger.error(f"Не удалось запустить {CADDY_CONTAINER}, пересоздаю: {e}")
            try:
                c.remove(force=True)
            except Exception as rm_err:
                logger.error(f"Не удалось удалить {CADDY_CONTAINER}: {rm_err}")
                return False
            entries = build_entries(db, k8s)
            _create_caddy(docker_client.client, build_caddyfile(entries, acme_email()))
            return True

    entries = build_entries(db, k8s)
    caddyfile = build_caddyfile(entries, acme_email())
    ensure_caddy(docker_client, caddyfile)
    return True


def apply_config(db, k8s=None) -> dict:
    """Пересобирает Caddyfile из активных доменов и применяет его.

    Никогда не бросает исключение: применение конфига — побочный эффект
    добавления/удаления домена, и его сбой не должен ронять сам запрос.
    Живёт здесь, а не в api/domains.py, потому что то же самое нужно фоновой
    доперепроверке доменов в воркере (autoverify_tick).
    """
    from app.core.docker_client import HostDockerClient

    try:
        docker_client = HostDockerClient()   # __init__ уже подключается
        if not docker_client.is_available():
            return {"applied": False, "reason": "Docker недоступен"}
        if k8s is None:
            from app.core.k8s_client import K8sClient
            k8s = K8sClient()
        entries = build_entries(db, k8s)
        caddyfile = build_caddyfile(entries, acme_email())
    except Exception as e:
        logger.error(f"Не удалось собрать конфиг Caddy: {e}")
        return {"applied": False, "reason": str(e)}
    try:
        ensure_caddy(docker_client, caddyfile)
        return {"applied": True, "sites": len(entries)}
    except Exception as e:
        logger.error(f"Не удалось применить конфиг Caddy: {e}")
        return {"applied": False, "reason": str(e)}


def verify_domain_row(db, dom, expected_ip: str) -> dict:
    """Одна проверка домена: владение (TXT) и маршрутизация (A).

    Порядок важен: пока владение не доказано, домен в конфиг не попадает,
    даже если A-запись уже указывает на этот сервер.
    """
    from datetime import datetime

    own_ok, own_detail = check_ownership(dom.domain, dom.verification_token)
    dns_ok, dns_detail = check_dns(dom.domain, expected_ip=expected_ip)

    dom.ownership_ok = own_ok
    dom.dns_ok = dns_ok
    dom.last_checked = datetime.utcnow()
    ready = own_ok and dns_ok
    dom.status = "active" if ready else "pending"
    dom.last_error = None if ready else (own_detail if not own_ok else dns_detail)
    db.commit()
    return {
        "ready": ready,
        "ownership_ok": own_ok, "ownership_detail": own_detail,
        "dns_ok": dns_ok, "detail": dns_detail,
    }


def autoverify_tick(k8s):
    """Доводит до готовности домены, которые ещё не прошли проверку.

    Нужен из-за задержки распространения DNS: записи создаются сразу (сами —
    см. services/dns_api.py, или руками у регистратора), а публичные
    резолверы видят их через десятки секунд. Проверять прямо в обработчике
    HTTP-запроса бессмысленно — он почти всегда упрётся в «ещё не видно», и
    пользователю пришлось бы жать «Проверить» вручную до победного.

    Тик дешёвый: пока нет ни одного неподтверждённого домена, не делается
    вообще ничего.
    """
    from app.db import SessionLocal
    from app.models.models import Domain

    db = SessionLocal()
    try:
        pending = db.query(Domain).filter(Domain.status != "active").all()
        if not pending:
            return
        became_ready = False
        for dom in pending:
            try:
                if verify_domain_row(db, dom, host_ip())["ready"]:
                    logger.info(f"Домен {dom.domain} подтверждён — включаю в конфиг прокси.")
                    became_ready = True
            except Exception as e:
                logger.warning(f"autoverify {dom.domain}: {e}")
        if became_ready:
            apply_config(db, k8s)
    finally:
        db.close()


def caddy_watchdog_tick(k8s):
    """Один тик вотчдога — вызывается периодически из воркера (см. worker.py).
    Сама владеет своими БД- и Docker-соединениями, чтобы вызывающая сторона
    оставалась однострочником, как и остальные демоны воркера."""
    from app.db import SessionLocal
    from app.core.docker_client import HostDockerClient

    docker_client = HostDockerClient()
    if not docker_client.client:
        return  # Docker недоступен — это отдельная проблема, не наша забота здесь
    db = SessionLocal()
    try:
        if reconcile_caddy(db, k8s, docker_client):
            logger.info(f"{CADDY_CONTAINER} восстановлен после зацикленного перезапуска.")
    finally:
        db.close()


def reload_caddy(docker_client):
    """Перечитывает конфиг без простоя."""
    c = docker_client.client.containers.get(CADDY_CONTAINER)
    res = c.exec_run(f"caddy reload --config {CADDYFILE_PATH} --adapter caddyfile")
    if res.exit_code != 0:
        raise RuntimeError(f"caddy reload: {res.output.decode(errors='ignore')[:300]}")
    return {"status": "reloaded"}


def stop_caddy(docker_client):
    import docker.errors
    try:
        c = docker_client.client.containers.get(CADDY_CONTAINER)
        c.stop()
        c.remove()
        return {"status": "stopped"}
    except docker.errors.NotFound:
        return {"status": "absent"}
