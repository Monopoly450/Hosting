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


def _create_caddy(cli, caddyfile: str):
    """Создаёт и запускает Caddy с нуля — общий путь и для первого запуска,
    и для восстановления после зацикленного рестарта (см. ensure_caddy)."""
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
            f"RestartCount={c.attrs.get('RestartCount', 0)}) — пересоздаю вместо попытки оживить."
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
        return False  # ещё не создавался — нечего лечить
    except Exception as e:
        logger.error(f"reconcile_caddy: не удалось получить контейнер {CADDY_CONTAINER}: {e}")
        return False

    state = _caddy_state(c)
    if state is None:
        return False

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
