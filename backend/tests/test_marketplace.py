import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import marketplace as mp


def test_catalog_integrity():
    ids = set()
    for app in mp.CATALOG:
        for key in ("id", "name", "description", "category", "icon", "app_port", "compose", "env"):
            assert key in app, f"{app.get('id')} missing {key}"
        assert app["id"] not in ids, "duplicate id"
        ids.add(app["id"])
        # публикуемый порт должен фигурировать в compose
        assert f'"{app["app_port"]}:' in app["compose"], f"{app['id']}: порт не опубликован"


def test_public_catalog_hides_compose_and_secret_values():
    pub = mp.get_catalog()
    assert len(pub) == len(mp.CATALOG)
    for a in pub:
        assert "compose" not in a
        for e in a["env"]:
            assert set(e.keys()) == {"key", "label", "secret", "generate"}
            assert "default" not in e  # значения секретов наружу не отдаём


def test_resolve_env_generates_secret():
    wp = mp.get_app("wordpress")
    env = mp.resolve_env(wp, {})
    assert env["DB_PASSWORD"]  # сгенерирован
    assert len(env["DB_PASSWORD"]) >= 16


def test_resolve_env_respects_override():
    wp = mp.get_app("wordpress")
    env = mp.resolve_env(wp, {"DB_PASSWORD": "my-secret"})
    assert env["DB_PASSWORD"] == "my-secret"


def test_build_cloud_init_contains_compose_and_env():
    wp = mp.get_app("wordpress")
    env = mp.resolve_env(wp, {"DB_PASSWORD": "abc123"})
    ci = mp.build_marketplace_cloud_init(wp, env, "vmpass")
    assert ci.startswith("#cloud-config")
    assert "docker-compose.yml" in ci
    assert "DB_PASSWORD=abc123" in ci
    assert "wordpress:6" in ci
    assert "docker compose up -d" in ci


def test_get_app_unknown():
    assert mp.get_app("does-not-exist") is None
