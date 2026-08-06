"""cloud-init обязан быть валидным YAML для КАЖДОГО сочетания ОС и шаблона.

Инцидент, ради которого написан этот файл: команда шаблона содержала
«своим сайтом: /var/www/html/index.php». Двоеточие с пробелом внутри
неэкранированного скаляра — и YAML разобрал элемент runcmd как СЛОВАРЬ
вместо строки. Документ при этом остаётся формально валидным, ошибки разбора
нет, поэтому ни один прежний тест ничего не заметил: они смотрели на список
команд до подстановки в YAML. А cloud-init на таком элементе спотыкается, и
runcmd не выполняется дальше вообще — шаблоны переставали работать разом на
всех системах.

Отсюда и форма проверки: генерируем настоящий манифест, достаём из него
настоящий userData и разбираем его настоящим YAML-парсером.
"""
import yaml
import pytest

from app.api.vms import generate_linux_manifest
from app.services.os_profiles import OS_FAMILY, TEMPLATES, template_supported


def _user_data(os_type: str, template):
    class Req:
        name = "vm1"
        cpu_cores = 2
        memory_gb = 2
        disk_gb = 20
        custom_image = None
        packages = None
        network_drives = None
        custom_user_data = None
        iso_url = None
        ssh_key = None
        static_ip = "172.20.0.10"
        cluster_network = None

    Req.os_type = os_type
    Req.cloud_init_template = template
    manifest = generate_linux_manifest(Req(), "pw123")
    volumes = manifest["spec"]["template"]["spec"]["volumes"]
    ci = next(v for v in volumes if "cloudInitNoCloud" in v)["cloudInitNoCloud"]
    return ci["userData"]


def _combinations():
    for os_type in sorted(OS_FAMILY):
        for template in [None] + sorted(TEMPLATES):
            if template and not template_supported(template, os_type):
                continue
            yield os_type, template


ALL_COMBINATIONS = list(_combinations())


def test_the_matrix_is_actually_covered():
    """Защита от того, что проверка молча выродится в пустой прогон."""
    assert len(ALL_COMBINATIONS) > 50


@pytest.mark.parametrize("os_type,template", ALL_COMBINATIONS)
def test_cloud_config_parses_and_every_runcmd_is_a_string(os_type, template):
    user_data = _user_data(os_type, template)

    doc = yaml.safe_load(user_data)
    assert isinstance(doc, dict), f"{os_type}/{template}: cloud-config не словарь"

    for i, cmd in enumerate(doc.get("runcmd") or []):
        assert isinstance(cmd, str), (
            f"{os_type}/{template}: runcmd[{i}] разобрался как "
            f"{type(cmd).__name__}, а не строка — cloud-init на этом остановится: {cmd!r}"
        )

    for i, pkg in enumerate(doc.get("packages") or []):
        assert isinstance(pkg, str), f"{os_type}/{template}: packages[{i}] не строка"


def test_a_command_with_a_colon_survives_as_one_string():
    """Точное воспроизведение инцидента: двоеточие с пробелом в команде."""
    from app.services.cloudinit import yaml_runcmd_lines

    cmd = "echo 'сайт: /var/www/html' > /tmp/a"
    doc = yaml.safe_load("runcmd:\n" + yaml_runcmd_lines([cmd]))
    assert doc["runcmd"] == [cmd]


@pytest.mark.parametrize("cmd", [
    "echo 'путь: /tmp' > /a",           # двоеточие с пробелом
    'printf "%s" "a: b"',                # то же в двойных кавычках
    "echo '#not a comment'",             # решётка
    "echo '- not a list item'",          # дефис в начале значения
    "echo 'tab\there'",                  # управляющий символ
    "echo \"quote\\\"inside\"",          # кавычка внутри
    "echo 'кириллица и двоеточие: да'",  # не-ASCII вместе с двоеточием
    "echo '@reboot'",                    # зарезервированный в YAML символ
    "echo 'a % b'",
])
def test_special_characters_do_not_break_the_document(cmd):
    from app.services.cloudinit import yaml_runcmd_lines

    doc = yaml.safe_load("runcmd:\n" + yaml_runcmd_lines([cmd]))
    assert doc["runcmd"] == [cmd], f"команда исказилась: {cmd!r}"


def test_empty_commands_are_skipped_not_rendered_as_null():
    """Пустая строка не должна давать элемент null — cloud-init на нём падает."""
    from app.services.cloudinit import yaml_runcmd_lines

    doc = yaml.safe_load("runcmd:\n" + yaml_runcmd_lines(["ok", "", None]))
    assert doc["runcmd"] == ["ok"]


def test_lamp_index_page_command_reaches_the_guest_intact():
    """Именно та команда, что ломала всё, должна доезжать целиком."""
    doc = yaml.safe_load(_user_data("almalinux", "lamp"))
    index_cmds = [c for c in doc["runcmd"] if "index.php" in c]
    assert index_cmds, "команда записи индексной страницы потерялась"
    assert any("<?php" in c and c.strip().endswith("index.php") for c in index_cmds)


# ---------------------- Деплой из репозитория --------------------------------
# Здесь двоеточие приносит уже сам пользователь — в команде запуска.

DEPLOY_STACKS = ["compose", "dockerfile", "node", "python", "static", "custom"]


@pytest.mark.parametrize("stack", DEPLOY_STACKS)
def test_deploy_cloud_init_parses_for_every_stack(stack):
    from app.api.deployments import build_deploy_cloud_init

    ud = build_deploy_cloud_init(name="app1", repo_url="https://github.com/o/r",
                                 branch="main", stack=stack, app_port=3000,
                                 run_command=None, password="pw")
    doc = yaml.safe_load(ud)
    for i, cmd in enumerate(doc.get("runcmd") or []):
        assert isinstance(cmd, str), f"{stack}: runcmd[{i}] не строка: {cmd!r}"


@pytest.mark.parametrize("run_command", [
    "echo 'старт: ok' && npm start",
    "gunicorn -b 0.0.0.0:8000 app:app",
    'sh -c "echo \\"hi: there\\""',
    "node server.js # порт: 3000",
])
def test_user_supplied_run_command_cannot_break_the_deploy(run_command):
    """Команду запуска пишет пользователь. Двоеточие с пробелом в ней —
    совершенно обычное дело, и оно не должно ронять весь cloud-init."""
    from app.api.deployments import build_deploy_cloud_init

    ud = build_deploy_cloud_init(name="app1", repo_url="https://github.com/o/r",
                                 branch="main", stack="node", app_port=3000,
                                 run_command=run_command, password="pw")
    doc = yaml.safe_load(ud)
    assert all(isinstance(c, str) for c in doc["runcmd"]), \
        f"команда запуска {run_command!r} сломала runcmd"


def test_deploy_survives_a_branch_name_with_punctuation():
    from app.api.deployments import build_deploy_cloud_init

    ud = build_deploy_cloud_init(name="app1", repo_url="https://github.com/o/r",
                                 branch="feature/ABC-1: fix", stack="node",
                                 app_port=3000, run_command=None, password="pw")
    doc = yaml.safe_load(ud)
    assert all(isinstance(c, str) for c in doc["runcmd"])


def test_every_marketplace_app_produces_valid_cloud_init():
    """Каталог маркетплейса — тоже отдельный сборщик cloud-init."""
    from app.services.marketplace import (get_catalog, get_app, resolve_env,
                                          build_marketplace_cloud_init)

    catalog = get_catalog()
    apps = catalog if isinstance(catalog, list) else catalog.get("apps", catalog)
    assert apps, "каталог маркетплейса пуст — проверка выродилась бы в пустую"

    for entry in apps:
        slug = entry.get("slug") or entry.get("id") or entry.get("name")
        app = get_app(slug)
        ud = build_marketplace_cloud_init(app, resolve_env(app, {}), "pw123")
        doc = yaml.safe_load(ud)
        assert isinstance(doc, dict), slug
        for i, cmd in enumerate(doc.get("runcmd") or []):
            assert isinstance(cmd, str), f"{slug}: runcmd[{i}] не строка"
        # docker-compose.yml должен доехать до гостя неповреждённым
        files = {w["path"]: w.get("content", "") for w in (doc.get("write_files") or [])}
        assert "/opt/app/docker-compose.yml" in files, slug
        yaml.safe_load(files["/opt/app/docker-compose.yml"])


def test_marketplace_compose_up_retries_instead_of_giving_up_once():
    """Образы приложений весят под гигабайт. Одна неудачная попытка —
    недоступное зеркало, не поднявшийся демон docker — оставляла приложение
    ненастроенным навсегда: ошибку гасил `|| true`, а повторять было некому.
    Снаружи это «ВМ запущена, а сайт не открывается»."""
    from app.services.marketplace import (get_app, resolve_env,
                                          build_marketplace_cloud_init)

    doc = yaml.safe_load(build_marketplace_cloud_init(
        get_app("nextcloud"), resolve_env(get_app("nextcloud"), {}), "pw"))
    compose_cmd = next(c for c in doc["runcmd"] if "compose up -d" in c)
    assert "while" in compose_cmd, "запуск compose должен повторяться"
    assert "break" in compose_cmd, "успешная попытка должна прекращать цикл"


def test_marketplace_waits_for_the_docker_daemon_before_using_it():
    """`systemctl enable --now docker` возвращает управление раньше, чем
    dockerd начинает принимать команды."""
    from app.services.marketplace import (get_app, resolve_env,
                                          build_marketplace_cloud_init)

    doc = yaml.safe_load(build_marketplace_cloud_init(
        get_app("nextcloud"), resolve_env(get_app("nextcloud"), {}), "pw"))
    wait_at = next(i for i, c in enumerate(doc["runcmd"]) if "docker info" in c)
    up_at = next(i for i, c in enumerate(doc["runcmd"]) if "compose up -d" in c)
    assert wait_at < up_at


def test_compose_retry_is_bounded():
    """Неограниченный цикл подвесил бы cloud-init навсегда — этим мы уже
    обжигались на ожидании сети."""
    from app.services.cloudinit import COMPOSE_UP_RUNCMD

    assert "-le 10" in COMPOSE_UP_RUNCMD and "-le 30" in COMPOSE_UP_RUNCMD


# ------------ apt-кэш должен обновляться перед декларативной установкой -----
# Инцидент с живого сервера: docker.io не установился («docker: not found» в
# runcmd), хотя стоял в packages. qemu-guest-agent чуть ниже в том же логе
# встал нормально — потому что его установка сама делает apt-get update перед
# install, а декларативный packages: без package_update — нет, и ставит из
# кэша, запечённого в образ при сборке. Если тот кэш успел устареть, apt не
# находит пакет и молча проваливает установку: cloud-init не останавливается,
# просто идёт в runcmd дальше как ни в чём не бывало.

@pytest.mark.parametrize("os_type,template", ALL_COMBINATIONS)
def test_package_cache_is_refreshed_before_declarative_install(os_type, template):
    doc = yaml.safe_load(_user_data(os_type, template))
    if doc.get("packages"):
        assert doc.get("package_update") is True, (
            f"{os_type}/{template}: packages есть, а package_update: true — нет; "
            f"установка может провалиться на устаревшем кэше apt/dnf/zypper"
        )


def test_marketplace_refreshes_the_cache_before_installing_docker():
    from app.services.marketplace import (get_app, resolve_env,
                                          build_marketplace_cloud_init)

    for entry_id in ("n8n", "nextcloud", "wordpress"):
        doc = yaml.safe_load(build_marketplace_cloud_init(
            get_app(entry_id), resolve_env(get_app(entry_id), {}), "pw"))
        assert doc.get("package_update") is True, entry_id


def test_deploy_refreshes_the_cache_before_installing_the_stack():
    from app.api.deployments import build_deploy_cloud_init

    for stack in DEPLOY_STACKS:
        doc = yaml.safe_load(build_deploy_cloud_init(
            name="app1", repo_url="https://github.com/o/r", branch="main",
            stack=stack, app_port=3000, run_command=None, password="pw"))
        assert doc.get("package_update") is True, stack
