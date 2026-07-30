"""Провижининг контейнеров, которые панель поднимает сама (реестр и Caddy).

Оба бага здесь пойманы только на живом сервере:

* `containers.create()` не скачивает образ (в отличие от `containers.run()`),
  и провижининг падал с «No such image: registry:2»;
* `put_archive()` требует существующий каталог-получатель, а `/auth` в образе
  registry:2 отсутствует — файл htpasswd было некуда положить.
"""
import os
import sys
import tarfile
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.docker_client import ensure_image
from app.services import registry as reg
from app.services import domains as dsvc


class ImageNotFound(Exception):
    pass


class FakeImages:
    def __init__(self, present):
        self.present = set(present)
        self.pulled = []

    def get(self, name):
        if name not in self.present:
            from docker.errors import ImageNotFound as RealNotFound
            raise RealNotFound(f"No such image: {name}")
        return object()

    def pull(self, name):
        self.pulled.append(name)
        self.present.add(name)


# ----------------------------- ensure_image ---------------------------------

def test_missing_image_is_pulled():
    cli = types.SimpleNamespace(images=FakeImages(present=[]))
    assert ensure_image(cli, "registry:2") is True
    assert cli.images.pulled == ["registry:2"]


def test_present_image_is_not_pulled():
    cli = types.SimpleNamespace(images=FakeImages(present=["registry:2"]))
    assert ensure_image(cli, "registry:2") is False
    assert cli.images.pulled == []


# --------------------- htpasswd попадает в существующий путь ----------------

def test_htpasswd_target_directory_is_not_auth():
    """`/auth` в образе registry:2 не существует — put_archive туда падает."""
    assert os.path.dirname(reg.HTPASSWD_PATH) != "/auth"
    assert os.path.dirname(reg.HTPASSWD_PATH) == "/etc"


def test_tar_member_name_matches_target_path():
    """Имя в архиве должно совпадать с basename пути, иначе registry
    не найдёт файл, который мы положили."""
    buf = reg._htpasswd_tar("aegis:$2b$hash")
    with tarfile.open(fileobj=buf, mode="r") as tar:
        names = tar.getnames()
    assert names == [os.path.basename(reg.HTPASSWD_PATH)]


def test_registry_env_points_at_the_file_we_write():
    """Путь в REGISTRY_AUTH_HTPASSWD_PATH и путь записи — одно и то же."""
    assert reg.HTPASSWD_PATH.startswith("/etc/")


# ------------------------- провижининг реестра ------------------------------

class FakeContainer:
    def __init__(self):
        self.archives = []
        self.started = False

    def put_archive(self, path, data):
        self.archives.append(path)
        return True

    def start(self):
        self.started = True


class FakeContainers:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.created = None
        self.create_kwargs = None

    def get(self, name):
        if name not in self.existing:
            from docker.errors import NotFound
            raise NotFound(f"no such container {name}")
        return self.existing[name]

    def create(self, image, **kwargs):
        self.create_kwargs = dict(kwargs, image=image)
        self.created = FakeContainer()
        return self.created


def test_provision_pulls_image_then_creates(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path))
    images = FakeImages(present=[])          # образа нет, как на чистом сервере
    containers = FakeContainers()
    client = types.SimpleNamespace(
        client=types.SimpleNamespace(images=images, containers=containers)
    )

    result = reg.provision_registry(client)

    assert images.pulled == [reg.REGISTRY_IMAGE], "образ должен скачиваться"
    assert result["status"] == "created"
    # конфиг положен в существующий каталог и контейнер запущен
    assert containers.created.archives == ["/etc"]
    assert containers.created.started
    # аутентификация включена
    env = containers.create_kwargs["environment"]
    assert env["REGISTRY_AUTH"] == "htpasswd"
    assert env["REGISTRY_AUTH_HTPASSWD_PATH"] == reg.HTPASSWD_PATH


def test_caddy_provision_pulls_image(monkeypatch):
    images = FakeImages(present=[])
    containers = FakeContainers()
    client = types.SimpleNamespace(
        client=types.SimpleNamespace(images=images, containers=containers)
    )

    dsvc.ensure_caddy(client, "example.com {\n\treverse_proxy 1.2.3.4:80\n}\n")

    assert images.pulled == [dsvc.CADDY_IMAGE], "образ Caddy должен скачиваться"
    assert containers.created.started
    assert containers.created.archives == [os.path.dirname(dsvc.CADDYFILE_PATH)]
