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
        for key in ("id", "name", "description", "category", "icon", "app_port", "env"):
            assert key in app, f"{app.get('id')} missing {key}"
        assert app["id"] not in ids, "duplicate id"
        ids.add(app["id"])
        if mp.is_template_app(app):
            # Окружение — не compose-стек: у него имя шаблона из os_profiles,
            # а cloud-init собирает воркер (см. модуль marketplace).
            assert "compose" not in app, f"{app['id']}: у окружения не должно быть compose"
            assert app["template"], f"{app['id']}: не указан шаблон"
        else:
            assert "compose" in app, f"{app['id']} missing compose"
            # публикуемый порт должен фигурировать в compose
            assert f'"{app["app_port"]}:' in app["compose"], f"{app['id']}: порт не опубликован"


def test_every_template_app_points_at_a_real_template():
    """Опечатка в имени шаблона иначе всплыла бы только при деплое: воркер
    молча собрал бы ВМ без окружения (build_template_steps на неизвестное имя
    отдаёт пустые списки)."""
    from app.services.os_profiles import TEMPLATES, template_offered

    tpl_apps = [a for a in mp.CATALOG if mp.is_template_app(a)]
    assert tpl_apps, "в каталоге нет ни одного окружения"
    for app in tpl_apps:
        assert app["template"] in TEMPLATES, f"{app['id']}: нет такого шаблона"
        # Маркетплейс всегда разворачивает Ubuntu — шаблон обязан быть для неё
        # доступен, иначе запись в каталоге есть, а окружения в ВМ не будет.
        assert template_offered(app["template"], "ubuntu"), app["id"]


def test_all_templates_from_os_profiles_are_offered_in_the_marketplace():
    """Шаблоны убрали из формы создания локальной ВМ, поэтому маркетплейс —
    единственная точка входа. Забытый шаблон стал бы недоступен вообще."""
    from app.services.os_profiles import TEMPLATES

    in_catalog = {a["template"] for a in mp.CATALOG if mp.is_template_app(a)}
    assert set(TEMPLATES) == in_catalog


def test_grafana_is_available_both_as_app_and_as_environment():
    """Grafana нужна и как готовое приложение (compose), и как шаблон — второй
    вариант используется в кластерах, где выбирается именно cloud_init_template."""
    from app.services.os_profiles import TEMPLATES

    app = mp.get_app("grafana")
    assert app and not mp.is_template_app(app)
    assert app["app_port"] == 3000
    assert "grafana/grafana-oss" in app["compose"]
    assert "grafana" in TEMPLATES


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
        if mp.is_template_app(app):
            continue  # окружения собирает воркер, у них нет compose
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


# ----------------- окружения: сеть и порты как у обычной ВМ -----------------
#
# Окружения из маркетплейса намеренно НЕ имеют своего сборщика cloud-init: имя
# шаблона уходит в VMTask.cloud_init_template, и всё остальное делает
# generate_linux_manifest — тот же, что для локальной ВМ и для ВМ в кластере.
# Тесты ниже закрепляют именно это: любой второй путь сборки сети рано или
# поздно разошёлся бы с основным (так уже было с netplan-файлом, который
# работал только в Ubuntu).

class _TplReq:
    """Минимальный запрос под generate_linux_manifest — как FakeReq в
    test_os_profiles, но с шаблоном из записи маркетплейса."""

    def __init__(self, template, static_ip="172.20.0.55", cluster_network=None):
        self.name = "mp-vm"
        self.os_type = "ubuntu"
        self.cpu_cores = 2
        self.memory_gb = 2
        self.disk_gb = 20
        self.custom_image = None
        self.packages = None
        self.network_drives = None
        self.cloud_init_template = template
        self.custom_user_data = None
        self.iso_url = None
        self.ssh_key = None
        self.static_ip = static_ip
        self.cluster_network = cluster_network


def _cloudinit_of(manifest):
    vols = manifest["spec"]["template"]["spec"]["volumes"]
    for v in vols:
        if "cloudInitNoCloud" in v:
            return v["cloudInitNoCloud"]
    raise AssertionError("в манифесте нет cloudInitNoCloud")


def test_template_app_gets_static_ip_through_networkdata():
    """Сеть окружению задаёт networkData манифеста, а не свой netplan-файл."""
    import yaml
    from app.api.vms import generate_linux_manifest

    ci = _cloudinit_of(generate_linux_manifest(_TplReq("lamp"), "pw"))
    assert "/etc/netplan" not in ci["userData"]
    nd = yaml.safe_load(ci["networkData"])
    assert nd["ethernets"]["stable-nic"]["addresses"] == ["172.20.0.55/24"]


def test_every_template_app_produces_valid_cloud_init_with_its_steps():
    """Шаблон должен реально доехать до ВМ: проверяем, что cloud-init
    парсится и что в нём есть команды/пакеты именно этого окружения."""
    import yaml
    from app.api.vms import generate_linux_manifest
    from app.services.os_profiles import build_template_steps

    tpl_apps = [a for a in mp.CATALOG if mp.is_template_app(a)]
    assert tpl_apps
    for app in tpl_apps:
        tpl = app["template"]
        ci = _cloudinit_of(generate_linux_manifest(_TplReq(tpl), "pw"))
        doc = yaml.safe_load(ci["userData"])
        assert isinstance(doc, dict), tpl
        for i, cmd in enumerate(doc.get("runcmd") or []):
            assert isinstance(cmd, str), f"{tpl}: runcmd[{i}] не строка"

        packages, commands = build_template_steps(tpl, "ubuntu")
        rendered = yaml.safe_dump(doc, allow_unicode=True)
        for pkg in packages:
            assert pkg in rendered, f"{tpl}: пакет {pkg} не попал в cloud-init"
        if commands:
            assert commands[0] in (doc.get("runcmd") or []), tpl


def test_template_app_in_a_cluster_keeps_both_interfaces():
    """В кластере у ВМ два интерфейса: pod-сеть (интернет как страховка) и
    сеть кластера через Multus. Окружение не должно ломать этот путь."""
    import yaml
    from app.api.vms import generate_linux_manifest

    spec = generate_linux_manifest(
        _TplReq("grafana", cluster_network="cluster-net"), "pw"
    )["spec"]["template"]["spec"]

    networks = {n["name"]: n for n in spec["networks"]}
    assert networks["default"]["pod"] == {}
    assert networks["clusternet"]["multus"]["networkName"] == "cluster-net"

    ifaces = {i["name"]: i for i in spec["domain"]["devices"]["interfaces"]}
    assert set(ifaces) == {"default", "clusternet"}
    assert "masquerade" in ifaces["default"]
    assert "bridge" in ifaces["clusternet"]
    # MAC детерминирован от имени ВМ — стабилен между пересозданиями
    assert ifaces["default"]["macAddress"] != ifaces["clusternet"]["macAddress"]

    # Стабильный IP по-прежнему приезжает через networkData, а не netplan
    ci = _cloudinit_of(generate_linux_manifest(
        _TplReq("grafana", cluster_network="cluster-net"), "pw"))
    nd = yaml.safe_load(ci["networkData"])
    assert nd["ethernets"]["stable-nic"]["addresses"] == ["172.20.0.55/24"]
