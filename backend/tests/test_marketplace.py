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


def test_add_public_url():
    env = mp.add_public_url({"A": "1"}, "10.0.0.5", 28042)
    assert env["PUBLIC_HOST"] == "10.0.0.5:28042"
    assert env["PUBLIC_URL"] == "http://10.0.0.5:28042"
    assert env["A"] == "1"  # исходные значения не теряются


def test_apps_needing_public_url_reference_it():
    """Приложения, которые сами генерируют ссылки, должны получать свой внешний
    адрес — иначе ссылки будут указывать на localhost."""
    for app_id in ("ghost", "wordpress", "nextcloud", "n8n", "vaultwarden"):
        compose = mp.get_app(app_id)["compose"]
        assert "${PUBLIC_URL}" in compose or "${PUBLIC_HOST}" in compose, app_id


def test_generated_cloud_init_and_compose_are_valid_yaml():
    """Compose встраивается в cloud-init с отступами — проверяем, что оба
    документа действительно парсятся и порт приложения опубликован."""
    import yaml
    for app in mp.CATALOG:
        env = mp.add_public_url(mp.resolve_env(app, {}), "10.0.0.5", 28042)
        ci = mp.build_marketplace_cloud_init(app, env, "pw")

        doc = yaml.safe_load(ci)
        files = {f["path"]: f["content"] for f in doc["write_files"]}
        assert "/opt/app/docker-compose.yml" in files, app["id"]

        compose = yaml.safe_load(files["/opt/app/docker-compose.yml"])
        assert compose.get("services"), app["id"]
        ports = [p for s in compose["services"].values() for p in s.get("ports", [])]
        assert any(p.startswith(f"{app['app_port']}:") for p in ports), app["id"]

        env_file = files["/opt/app/.env"]
        assert "PUBLIC_URL=http://10.0.0.5:28042" in env_file, app["id"]


def test_public_url_lands_in_cloud_init():
    ghost = mp.get_app("ghost")
    env = mp.add_public_url(mp.resolve_env(ghost, {}), "10.0.0.5", 28042)
    ci = mp.build_marketplace_cloud_init(ghost, env, "pw")
    # значение попадает в .env, а compose ссылается на него
    assert "PUBLIC_URL=http://10.0.0.5:28042" in ci
    assert "url: ${PUBLIC_URL}" in ci
