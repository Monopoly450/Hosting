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

logger = logging.getLogger("app.services.domains")

CADDY_CONTAINER = "aegis-caddy"
CADDY_VOLUME = "aegis-caddy-data"      # тут Caddy хранит сертификаты
CADDY_IMAGE = "caddy:2"
CADDYFILE_PATH = "/etc/caddy/Caddyfile"

# Метка домена: буквы/цифры/дефис, до 63 символов; минимум два уровня.
DOMAIN_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


def host_ip() -> str:
    from app.core.netutils import detect_host_ip
    return detect_host_ip()


def acme_email() -> str:
    return os.getenv("ACME_EMAIL", "")


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
        lines.append(f"\treverse_proxy {e['upstream']}")
        lines.append("}")
        lines.append("")

    if not entries:
        # Пустой конфиг невалиден — оставляем заглушку, чтобы Caddy стартовал.
        lines.append("# нет активных доменов")
        lines.append(":8080 {")
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
    try:
        answers = dns.resolver.resolve(name, "TXT")
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

    entries = []
    ready = db.query(Domain).filter(
        Domain.dns_ok == True, Domain.ownership_ok == True  # noqa: E712
    ).all()
    for dom in ready:
        upstream, err = resolve_upstream(db, k8s, dom)
        if upstream:
            entries.append({"domain": dom.domain, "upstream": upstream})
    return entries


# --------------------------- Управление Caddy -------------------------------

def caddy_status(docker_client) -> dict:
    info = {"docker": False, "running": False, "host_ip": host_ip()}
    if not docker_client or not docker_client.is_available():
        return info
    info["docker"] = True
    try:
        c = docker_client.client.containers.get(CADDY_CONTAINER)
        info["running"] = (c.status == "running")
    except Exception:
        info["running"] = False
    return info


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


def ensure_caddy(docker_client, caddyfile: str):
    """Создаёт (если нужно) и запускает Caddy с актуальным конфигом."""
    import docker.errors
    cli = docker_client.client
    try:
        c = cli.containers.get(CADDY_CONTAINER)
    except docker.errors.NotFound:
        from app.core.docker_client import ensure_image
        ensure_image(cli, CADDY_IMAGE, "(первый запуск может занять минуту)")

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
        return {"status": "created"}

    c.put_archive(os.path.dirname(CADDYFILE_PATH), _caddyfile_tar(caddyfile))
    if c.status != "running":
        c.start()
        return {"status": "started"}
    return reload_caddy(docker_client)


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
