"""API приватного Docker-реестра (только для администратора)."""
import logging
import urllib.error

from fastapi import APIRouter, HTTPException, Depends

from app.core.docker_client import HostDockerClient
from app.services import registry as reg

router = APIRouter()
logger = logging.getLogger("app.api.registry")


def get_docker_client():
    client = HostDockerClient()
    client.connect()
    return client


def _client() -> reg.RegistryClient:
    creds = reg.load_credentials()
    auth = (creds["user"], creds["password"]) if creds else None
    return reg.RegistryClient(auth=auth)


def _guard_registry_call(fn):
    """Единая обработка недоступности реестра."""
    try:
        return fn()
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        raise HTTPException(status_code=503, detail=f"Реестр недоступен (не запущен?): {e}")


@router.get("/status")
def status(client: HostDockerClient = Depends(get_docker_client)):
    return reg.registry_status(client)


@router.post("/provision")
def provision(client: HostDockerClient = Depends(get_docker_client)):
    if not client.is_available():
        raise HTTPException(status_code=503, detail="Docker недоступен на хосте")
    try:
        return reg.provision_registry(client)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось запустить реестр: {e}")


@router.post("/stop")
def stop(client: HostDockerClient = Depends(get_docker_client)):
    if not client.is_available():
        raise HTTPException(status_code=503, detail="Docker недоступен на хосте")
    return reg.stop_registry(client)


@router.get("/repositories")
def repositories():
    repos = _guard_registry_call(lambda: _client().list_repositories())
    out = []
    for name in repos:
        try:
            tags = _client().list_tags(name)
        except Exception:
            tags = []
        out.append({"name": name, "tags_count": len(tags)})
    return out


def _check_repo(repo: str):
    if not reg.is_valid_repo(repo):
        raise HTTPException(status_code=400, detail="Некорректное имя репозитория")


def _check_tag(tag: str):
    if not reg.is_valid_tag(tag):
        raise HTTPException(status_code=400, detail="Некорректное имя тега")


@router.get("/repositories/{repo:path}/tags")
def tags(repo: str):
    _check_repo(repo)
    return {"repo": repo, "tags": _guard_registry_call(lambda: _client().list_tags(repo))}


@router.delete("/repositories/{repo:path}/tags/{tag}")
def delete_tag(repo: str, tag: str):
    _check_repo(repo)
    _check_tag(tag)
    try:
        _guard_registry_call(lambda: _client().delete_tag(repo, tag))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось удалить тег: {e}")
    return {"status": "deleted", "repo": repo, "tag": tag}


@router.get("/info")
def info():
    host = reg.push_host()
    creds = reg.load_credentials()
    user = creds["user"] if creds else reg.REGISTRY_USER
    password = creds["password"] if creds else None
    return {
        "push_host": host,
        "endpoint": reg.registry_base_url(),
        "username": user,
        "password": password,   # виден только администратору (роутер admin-gated)
        "insecure_note": (
            "Реестр работает по HTTP. Добавьте его в insecure-registries демона Docker: "
            f'{{"insecure-registries": ["{host}"]}} в /etc/docker/daemon.json и перезапустите docker.'
        ),
        "examples": [
            f"echo '<пароль>' | docker login {host} -u {user} --password-stdin",
            f"docker tag my-image:latest {host}/my-image:latest",
            f"docker push {host}/my-image:latest",
            f"docker pull {host}/my-image:latest",
        ],
    }
