"""Приватный Docker-реестр: провижининг контейнера registry:2 на хосте
и клиент к его HTTP API v2 (список репозиториев, тегов, удаление образов).
"""
import base64
import json
import logging
import os
import re
import secrets
import urllib.request

logger = logging.getLogger("app.services.registry")

REGISTRY_CONTAINER = "aegis-registry"
REGISTRY_VOLUME = "aegis-registry-data"
REGISTRY_IMAGE = "registry:2"
REGISTRY_PORT = int(os.getenv("REGISTRY_PORT", "5000"))
REGISTRY_USER = "aegis"
REGISTRY_REALM = "Aegis Registry"
# Файл кладём в /etc: put_archive требует, чтобы каталог-получатель уже
# существовал в образе, а привычного /auth в registry:2 нет — из-за этого
# провижининг падал с «no such file or directory».
HTPASSWD_PATH = "/etc/registry-htpasswd"
MANIFEST_ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"


def _data_dir() -> str:
    # /app/data смонтирован из ./data и переживает пересоздание контейнера
    return os.getenv("AEGIS_DATA_DIR") or os.path.dirname(
        os.getenv("IMAGES_DIR", "/app/data/images")
    ) or "/app/data"


def _creds_path() -> str:
    return os.path.join(_data_dir(), "registry_auth")


def load_credentials():
    """Возвращает {'user','password'} или None, если реестр ещё не провижинили."""
    from app.core.crypto import decrypt_secret
    path = _creds_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.loads(decrypt_secret(f.read().strip()))
    except Exception as e:
        logger.warning(f"registry creds read failed: {e}")
        return None


def load_or_create_credentials() -> dict:
    """Как load_credentials, но при отсутствии генерирует и сохраняет пароль."""
    from app.core.crypto import encrypt_secret
    creds = load_credentials()
    if creds:
        return creds
    creds = {"user": REGISTRY_USER, "password": secrets.token_hex(24)}
    path = _creds_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(encrypt_secret(json.dumps(creds)))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return creds


def htpasswd_entry(user: str, password: str) -> str:
    """Строка htpasswd с bcrypt-хэшем (формат, который понимает registry:2)."""
    import bcrypt
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    return f"{user}:{hashed.decode()}"

# Имена репозиториев и тегов подставляются в URL запроса к реестру, поэтому
# проверяем их по формату Docker: каждый сегмент обязан начинаться с буквы или
# цифры. Это заодно исключает "..", ведущий за пределы своего репозитория.
_SEGMENT = r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
REPO_RE = re.compile(rf"^{_SEGMENT}(?:/{_SEGMENT})*$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")


def is_valid_repo(name: str) -> bool:
    return bool(name) and len(name) <= 255 and bool(REPO_RE.match(name))


def is_valid_tag(tag: str) -> bool:
    return bool(tag) and bool(TAG_RE.match(tag))


def registry_base_url() -> str:
    return f"http://localhost:{REGISTRY_PORT}"


def push_host(host: str = None) -> str:
    """Адрес для docker login/push. Если передан host — используем его
    (он берётся из того, как открыта панель), иначе определяем сами."""
    from app.core.netutils import detect_host_ip
    return f"{host or detect_host_ip()}:{REGISTRY_PORT}"


# ------------------------------- HTTP-клиент v2 -----------------------------

class RegistryClient:
    def __init__(self, base_url: str = None, auth: tuple = None):
        self.base = (base_url or registry_base_url()).rstrip("/")
        self.auth = auth  # (user, password) или None

    def _auth_header(self) -> dict:
        if not self.auth or not self.auth[0]:
            return {}
        raw = f"{self.auth[0]}:{self.auth[1]}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    def _request(self, path, method="GET", headers=None):
        hdrs = dict(headers or {})
        hdrs.update(self._auth_header())
        req = urllib.request.Request(self.base + path, method=method, headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()

    def list_repositories(self) -> list:
        _, _, body = self._request("/v2/_catalog")
        return json.loads(body or b"{}").get("repositories") or []

    def list_tags(self, repo: str) -> list:
        _, _, body = self._request(f"/v2/{repo}/tags/list")
        return json.loads(body or b"{}").get("tags") or []

    def get_digest(self, repo: str, tag: str):
        _, headers, _ = self._request(
            f"/v2/{repo}/manifests/{tag}", method="HEAD", headers={"Accept": MANIFEST_ACCEPT}
        )
        return headers.get("Docker-Content-Digest")

    def delete_tag(self, repo: str, tag: str):
        digest = self.get_digest(repo, tag)
        if not digest:
            raise RuntimeError("Не удалось определить digest образа")
        status, _, _ = self._request(f"/v2/{repo}/manifests/{digest}", method="DELETE")
        return status


# ------------------------------- Провижининг --------------------------------

def registry_status(docker_client, host: str = None) -> dict:
    """Статус реестра: доступен ли docker и запущен ли контейнер."""
    info = {
        "docker": False, "running": False,
        "endpoint": registry_base_url(), "push_host": push_host(host),
    }
    if not docker_client or not docker_client.is_available():
        return info
    info["docker"] = True
    try:
        c = docker_client.client.containers.get(REGISTRY_CONTAINER)
        info["running"] = (c.status == "running")
    except Exception:
        info["running"] = False
    return info


def _htpasswd_tar(content: str):
    """Упаковывает htpasswd в tar для put_archive.

    Имя внутри архива обязано совпадать с basename HTPASSWD_PATH — иначе файл
    появится под другим именем и registry его не найдёт.
    """
    import io
    import tarfile
    data = content.encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=os.path.basename(HTPASSWD_PATH))
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def _has_auth(container) -> bool:
    """Проверяет, поднят ли контейнер с включённой аутентификацией."""
    try:
        env = container.attrs.get("Config", {}).get("Env", []) or []
        return any(str(e).startswith("REGISTRY_AUTH=") for e in env)
    except Exception:
        return False


def provision_registry(docker_client):
    """Поднимает registry:2 с обязательной аутентификацией (htpasswd/bcrypt).

    Реестр слушает на всех интерфейсах, поэтому без пароля любой, кто дотянется
    до порта, мог бы пушить и удалять образы. Пароль генерируется автоматически
    и хранится зашифрованным; повторный вызов возвращает те же учётные данные.
    """
    import docker.errors
    cli = docker_client.client
    creds = load_or_create_credentials()

    try:
        c = cli.containers.get(REGISTRY_CONTAINER)
        # Старый контейнер без аутентификации пересоздаём (том с образами цел).
        if not _has_auth(c):
            logger.warning("Пересоздаю реестр: у существующего контейнера нет аутентификации")
            try:
                c.stop()
            except Exception:
                pass
            c.remove(force=True)
        else:
            if c.status != "running":
                c.start()
            return {"status": "running", "endpoint": registry_base_url()}
    except docker.errors.NotFound:
        pass

    from app.core.docker_client import ensure_image
    ensure_image(cli, REGISTRY_IMAGE, "(первый запуск может занять минуту)")

    container = cli.containers.create(
        REGISTRY_IMAGE,
        name=REGISTRY_CONTAINER,
        detach=True,
        restart_policy={"Name": "always"},
        ports={"5000/tcp": REGISTRY_PORT},
        environment={
            "REGISTRY_STORAGE_DELETE_ENABLED": "true",
            "REGISTRY_AUTH": "htpasswd",
            "REGISTRY_AUTH_HTPASSWD_REALM": REGISTRY_REALM,
            "REGISTRY_AUTH_HTPASSWD_PATH": HTPASSWD_PATH,
        },
        volumes={REGISTRY_VOLUME: {"bind": "/var/lib/registry", "mode": "rw"}},
    )
    container.put_archive(os.path.dirname(HTPASSWD_PATH),
                          _htpasswd_tar(htpasswd_entry(creds["user"], creds["password"])))
    container.start()
    return {"status": "created", "endpoint": registry_base_url()}


def stop_registry(docker_client):
    import docker.errors
    cli = docker_client.client
    try:
        c = cli.containers.get(REGISTRY_CONTAINER)
        c.stop()
        c.remove()
        return {"status": "stopped"}
    except docker.errors.NotFound:
        return {"status": "absent"}
