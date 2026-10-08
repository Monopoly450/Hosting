"""Проверки docker-compose.yml, которые легко сломать незаметно.

Живой инцидент: `${CLOUDFLARE_TUNNEL_TOKEN:?...}` (обязательная переменная)
на сервисе `cloudflared` ломала КАЖДЫЙ `docker compose` (up, ps, даже
--help) на КАЖДОЙ установке — не только у тех, кто подключает Cloudflare
Tunnel. Причина: Docker Compose интерполирует переменные всех сервисов при
разборе файла и только потом фильтрует их по активным профилям — `profiles:`
не защищает `:?required` от срабатывания раньше времени.
"""
import os
import re

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _compose_text() -> str:
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        return f.read()


def _compose() -> dict:
    return yaml.safe_load(_compose_text())


def test_compose_file_is_valid_yaml():
    d = _compose()
    assert "cloudflared" in d["services"]


def test_minio_builds_locally_when_upstream_images_are_unavailable():
    svc = _compose()["services"]["minio"]
    assert svc["build"] == "./minio"
    assert svc["image"] == "aegis-minio:RELEASE.2025-09-07T16-13-09Z"
    assert svc["pull_policy"] == "build"
    assert "minio_data:/data" in svc["volumes"]
    assert svc["command"] == 'server /data --console-address ":9001"'


@pytest.mark.parametrize("arch,digest", [
    ("amd64", "01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891"),
    ("arm64", "14c8c9616cfce4636add161304353244e8de383b2e2752c0e9dad01d4c27c12c"),
])
def test_backend_mc_download_is_pinned_and_verified_for_target_architecture(arch, digest):
    with open(os.path.join(ROOT, "backend", "Dockerfile"), encoding="utf-8") as stream:
        dockerfile = stream.read()
    block = re.search(r"RUN mc_arch=.*?(?=\n\n)", dockerfile, re.S)
    assert block, "mc needs its own fail-fast install and executable check"
    install = block.group()
    assert 'dpkg --print-architecture' in install
    assert 'uname -m' not in install
    assert 'mc_release="RELEASE.2025-08-13T08-35-41Z"' in install
    assert f'{arch}) mc_sha="{digest}"' in install
    assert 'curl -fSL --retry 3' in install
    assert 'https://github.com/minio/mc/releases/download/' in install
    assert 'mc.linux-${mc_arch}.${mc_release}' in install
    assert install.index('sha256sum --check') < install.index('chmod 755') < install.index('mc --version')
    assert 'curl -sSL "https://dl.min.io' not in dockerfile


def test_backend_and_worker_share_the_verified_mc_image_build():
    services = _compose()["services"]
    assert services["backend"]["build"] == services["worker"]["build"]


@pytest.mark.parametrize("service", ["backend", "worker"])
@pytest.mark.parametrize("key", ["MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"])
def test_s3_clients_receive_the_same_credentials_as_minio(service, key):
    services = _compose()["services"]
    def environment(name):
        return dict(entry.split("=", 1) for entry in services[name]["environment"])
    expected = environment("minio")[key]
    assert environment(service).get(key) == expected, (
        f"{service} must receive {key} from .env, not use the Python fallback"
    )
    if key == "MINIO_ROOT_PASSWORD":
        assert "${MINIO_ROOT_PASSWORD:?" in expected


def test_no_required_variable_on_a_profiled_service():
    """Общий случай, а не только cloudflared: `:?` на переменной сервиса,
    у которого есть `profiles:`, ломает compose для всех, кто этот профиль
    не использует — с этим уже наступили один раз."""
    d = _compose()
    for name, svc in d["services"].items():
        if "profiles" not in svc:
            continue
        blob = yaml.dump(svc)
        assert ":?" not in blob, (
            f"сервис {name} под профилем использует обязательную переменную "
            f"(:?) — это ломает docker compose даже без активного профиля"
        )


def test_cloudflare_tunnel_token_has_a_safe_default():
    compose = _compose_text()
    m = re.search(r"cloudflared:.*?(?=\n  \w+:|\Z)", compose, re.S)
    assert m, "сервис cloudflared не найден в docker-compose.yml"
    block = m.group(0)
    assert "CLOUDFLARE_TUNNEL_TOKEN:-" in block
    assert "CLOUDFLARE_TUNNEL_TOKEN:?" not in block


def test_cloudflared_only_starts_under_its_own_profile():
    d = _compose()
    assert d["services"]["cloudflared"]["profiles"] == ["cloudflare"]


def test_mandatory_secrets_still_fail_fast():
    """Обратная сторона того же теста: пароли, нужные ВСЕГДА (не под
    профилем), обязаны остаться обязательными — иначе бэкенд молча
    стартует с пустым паролем к БД."""
    compose = _compose_text()
    for var in ("POSTGRES_PASSWORD", "ADMIN_TOKEN", "RABBITMQ_USER"):
        assert f"{{{var}:?" in compose, f"{var} должен быть обязательным"
