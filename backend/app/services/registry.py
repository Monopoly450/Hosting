"""Приватный Docker-реестр: провижининг контейнера registry:2 на хосте
и клиент к его HTTP API v2 (список репозиториев, тегов, удаление образов).
"""
import json
import logging
import os
import urllib.request

logger = logging.getLogger("app.services.registry")

REGISTRY_CONTAINER = "aegis-registry"
REGISTRY_VOLUME = "aegis-registry-data"
REGISTRY_IMAGE = "registry:2"
REGISTRY_PORT = int(os.getenv("REGISTRY_PORT", "5000"))
MANIFEST_ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"


def registry_base_url() -> str:
    return f"http://localhost:{REGISTRY_PORT}"


def push_host() -> str:
    host = os.getenv("AEGIS_HOST_IP") or os.getenv("HOST_IP") or "127.0.0.1"
    return f"{host}:{REGISTRY_PORT}"


# ------------------------------- HTTP-клиент v2 -----------------------------

class RegistryClient:
    def __init__(self, base_url: str = None):
        self.base = (base_url or registry_base_url()).rstrip("/")

    def _request(self, path, method="GET", headers=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {})
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

def registry_status(docker_client) -> dict:
    """Статус реестра: доступен ли docker и запущен ли контейнер."""
    info = {
        "docker": False, "running": False,
        "endpoint": registry_base_url(), "push_host": push_host(),
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


def provision_registry(docker_client):
    """Запускает (или включает существующий) контейнер registry:2 с удалением тегов."""
    import docker.errors
    cli = docker_client.client
    try:
        c = cli.containers.get(REGISTRY_CONTAINER)
        if c.status != "running":
            c.start()
        return {"status": "running", "endpoint": registry_base_url()}
    except docker.errors.NotFound:
        pass
    cli.containers.run(
        REGISTRY_IMAGE,
        name=REGISTRY_CONTAINER,
        detach=True,
        restart_policy={"Name": "always"},
        ports={"5000/tcp": REGISTRY_PORT},
        environment={"REGISTRY_STORAGE_DELETE_ENABLED": "true"},
        volumes={REGISTRY_VOLUME: {"bind": "/var/lib/registry", "mode": "rw"}},
    )
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
