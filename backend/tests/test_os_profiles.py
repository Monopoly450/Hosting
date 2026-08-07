"""Шаблоны окружения и сеть должны быть корректны для КАЖДОЙ поддерживаемой ОС.

Раньше и пакеты шаблонов, и конфигурация сети были захардкожены под Debian
для всех 13 типов ОС в каталоге:

* `apache2`, `docker.io`, `redis-server`, `nfs-common` — дебиановские имена;
  в RHEL-семействе (CentOS/Rocky/Alma/Fedora) таких пакетов нет, установка
  падала, и шаблон молча не применялся — пользователь получал «чистую» ОС.
* `/etc/netplan/99-dhcp.yaml` — netplan есть только в Ubuntu. На восьми из
  десяти Linux-систем файл просто ложился на диск, никем не читаемый, и
  мостовой интерфейс оставался ненастроенным.
"""
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import yaml

from app.services.os_profiles import (
    TEMPLATES, build_template_steps, family_of, has_systemd,
    nfs_client_package, supported_templates_for, template_supported,
)


class FakeReq:
    """Минимальный аналог VMCreationRequest для generate_linux_manifest."""

    def __init__(self, os_type, template=None, static_ip="172.20.0.55", drives=None):
        self.name = "test-vm"
        self.os_type = os_type
        self.cpu_cores = 2
        self.memory_gb = 2
        self.disk_gb = 20
        self.custom_image = None
        self.packages = None
        self.network_drives = drives
        self.cloud_init_template = template
        self.custom_user_data = None
        self.iso_url = None
        self.ssh_key = None
        self.static_ip = static_ip
        self.cluster_network = None


def _cloudinit_of(manifest):
    for vol in manifest["spec"]["template"]["spec"]["volumes"]:
        if "cloudInitNoCloud" in vol:
            return vol["cloudInitNoCloud"]
    raise AssertionError("в манифесте нет тома cloudInitNoCloud")


def _all_linux_os_types():
    from app.api.vms import LINUX_CLOUD_IMAGES
    return sorted(LINUX_CLOUD_IMAGES)


# --------------------------- семейства и службы ---------------------------

def test_rhel_family_covers_every_rhel_derivative():
    for os_type in ("centos", "bitrix", "almalinux", "rocky", "fedora"):
        assert family_of(os_type) == "rhel", os_type


def test_alpine_has_no_systemd():
    assert has_systemd("alpine") is False
    assert has_systemd("ubuntu") is True


def test_nfs_package_name_differs_per_family():
    # Пакет NFS-клиента называется по-разному — с nfs-common сетевые диски
    # монтировались только на Debian/Ubuntu.
    assert nfs_client_package("ubuntu") == "nfs-common"
    assert nfs_client_package("rocky") == "nfs-utils"
    assert nfs_client_package("opensuse") == "nfs-client"


# --------------------------- пакеты шаблонов ---------------------------

def test_lamp_uses_httpd_not_apache2_on_rhel():
    packages, commands = build_template_steps("lamp", "rocky")
    assert "httpd" in packages
    assert "apache2" not in packages          # пакета с таким именем в RHEL нет
    assert "php-mysqlnd" in packages
    assert "php-mysql" not in packages        # дебиановское имя
    assert any("systemctl enable --now httpd" in c for c in commands)


def test_redis_package_and_service_name_differ_on_rhel():
    deb_pkgs, deb_cmds = build_template_steps("redis", "ubuntu")
    rhel_pkgs, rhel_cmds = build_template_steps("redis", "centos")
    assert deb_pkgs == ["redis-server"]
    assert rhel_pkgs == ["redis"]
    assert any("redis-server" in c for c in deb_cmds)
    assert any("--now redis" in c for c in rhel_cmds)


def test_postgresql_on_rhel_runs_initdb_before_start():
    packages, commands = build_template_steps("postgresql", "almalinux")
    assert "postgresql-server" in packages
    initdb_at = next(i for i, c in enumerate(commands) if "initdb" in c)
    start_at = next(i for i, c in enumerate(commands) if "enable --now postgresql" in c)
    # Без initdb кластер БД не создан и служба не стартует вообще
    assert initdb_at < start_at


def test_docker_on_rhel_adds_repo_because_docker_io_does_not_exist():
    packages, commands = build_template_steps("docker", "centos")
    assert "docker.io" not in packages
    assert any("download.docker.com" in c for c in commands)


def test_alpine_uses_openrc_instead_of_systemctl():
    _, commands = build_template_steps("redis", "alpine")
    assert any("rc-update add redis default" in c for c in commands)
    assert not any(c.startswith("systemctl") for c in commands)


def test_portainer_reuses_docker_steps_of_the_same_family():
    docker_pkgs, docker_cmds = build_template_steps("docker", "ubuntu")
    port_pkgs, port_cmds = build_template_steps("portainer", "ubuntu")
    assert port_pkgs == docker_pkgs
    assert port_cmds[:len(docker_cmds)] == docker_cmds
    assert any("portainer/portainer-ce" in c for c in port_cmds)


def test_wordpress_chowns_to_the_right_web_user():
    _, deb = build_template_steps("wordpress", "ubuntu")
    _, rhel = build_template_steps("wordpress", "rocky")
    assert any("www-data:www-data" in c for c in deb)
    # В RHEL веб-сервер работает от apache, а a2enmod вообще не существует
    assert any("apache:apache" in c for c in rhel)
    assert not any("a2enmod" in c for c in rhel)


# --------------------------- поддержка шаблонов ---------------------------

def test_unsupported_pairs_are_reported_not_silently_wrong():
    # LAMP описан только для debian/rhel/suse — на Alpine его нет, и лучше
    # честно отказать, чем поставить несуществующие пакеты.
    assert template_supported("lamp", "ubuntu") is True
    assert template_supported("lamp", "alpine") is False
    assert template_supported("docker", "alpine") is True
    assert template_supported("", "alpine") is True       # без шаблона — всегда можно


def test_unsupported_template_yields_no_packages():
    packages, commands = build_template_steps("lamp", "alpine")
    assert packages == [] and commands == []


def test_every_os_supports_at_least_one_template():
    for os_type in _all_linux_os_types():
        assert supported_templates_for(os_type), os_type


def test_bitrix_rejects_only_the_templates_that_fight_for_port_80():
    """Реальный случай: Bitrix + LAMP отдавал «403 Forbidden от nginx/1.21.5».

    bitrix-env.sh разворачивает собственный стек — nginx впереди, за ним
    Apache, MySQL и PHP. LAMP ставил поверх ещё один Apache, оба стека делили
    порт 80, выигрывал nginx от Bitrix и отдавал 403, потому что сайт в нём
    ещё не настроен.

    Но это касается ТОЛЬКО шаблонов с веб-сервером. Docker портов не занимает,
    Portainer слушает 9000, Redis 6379, PostgreSQL 5432 (у Bitrix MySQL на
    3306) — им рядом с Bitrix ничего не мешает, и запрещать их не за что."""
    from app.services.os_profiles import OS_WITH_OWN_WEB_STACK, WEB_STACK_TEMPLATES

    assert "bitrix" in OS_WITH_OWN_WEB_STACK

    for template in WEB_STACK_TEMPLATES:
        assert template_supported(template, "bitrix") is False, template

    for template in ("docker", "portainer", "redis", "postgresql", "nodejs", "python"):
        assert template_supported(template, "bitrix") is True, template

    # ВМ без шаблона на Bitrix по-прежнему создаётся — это штатный сценарий
    assert template_supported("", "bitrix") is True


def test_web_stack_restriction_does_not_leak_to_other_rhel_systems():
    """Ограничение относится к Bitrix, а не ко всему семейству RHEL."""
    for os_type in ("centos", "rocky", "almalinux", "fedora"):
        assert template_supported("lamp", os_type) is True, os_type


# --------------------------- сеть в манифесте ---------------------------

@pytest.mark.parametrize("os_type", _all_linux_os_types())
def test_network_goes_to_networkdata_not_a_netplan_file(os_type):
    """Ключевая регрессия: netplan-файл работал только в Ubuntu."""
    from app.api.vms import generate_linux_manifest

    ci = _cloudinit_of(generate_linux_manifest(FakeReq(os_type), "pw"))
    assert "/etc/netplan" not in ci["userData"], os_type
    nd = yaml.safe_load(ci["networkData"])
    assert nd["version"] == 2
    assert nd["ethernets"]["stable-nic"]["addresses"] == ["172.20.0.55/24"]


@pytest.mark.parametrize("os_type", _all_linux_os_types())
def test_generated_cloud_init_is_valid_yaml_for_every_os(os_type):
    from app.api.vms import generate_linux_manifest

    for template in [None] + list(TEMPLATES):
        if template and not template_supported(template, os_type):
            continue
        ci = _cloudinit_of(generate_linux_manifest(FakeReq(os_type, template), "pw"))
        doc = yaml.safe_load(ci["userData"])
        assert doc.get("runcmd"), (os_type, template)


def test_systemd_only_bits_are_absent_on_alpine():
    from app.api.vms import generate_linux_manifest

    alpine = _cloudinit_of(generate_linux_manifest(FakeReq("alpine"), "pw"))["userData"]
    ubuntu = _cloudinit_of(generate_linux_manifest(FakeReq("ubuntu"), "pw"))["userData"]
    # Drop-in для getty — юнит systemd, в Alpine его читать некому
    assert "getty@tty1.service.d" in ubuntu
    assert "getty@tty1.service.d" not in alpine
    assert "systemctl daemon-reload" not in alpine


def test_network_drives_use_the_right_nfs_package():
    from app.api.vms import generate_linux_manifest

    ci = _cloudinit_of(generate_linux_manifest(FakeReq("rocky", drives="srv:/export"), "pw"))
    doc = yaml.safe_load(ci["userData"])
    assert "nfs-utils" in doc["packages"]
    assert "nfs-common" not in doc["packages"]


# --------------------- ожидание сети не должно висеть -----------------------

def test_network_wait_is_bounded_in_every_cloud_init_builder():
    """Реальная причина «шаблоны работают только на Ubuntu».

    Ожидание сети стояло как `while ! ping ...; do sleep 2; done` без верхней
    границы, а команды шаблона идут ПОСЛЕ него. Там, где исходящий ICMP закрыт
    (обычное дело в университетских и корпоративных сетях при рабочем HTTP),
    runcmd зависал навсегда.

    Ubuntu это маскировала: пакеты ставит модуль packages — он отрабатывает до
    runcmd, а политика пакетов Debian/Ubuntu стартует демон прямо при
    установке, поэтому сайт поднимался сам. В RHEL, SUSE, Arch и Alpine службы
    после установки не стартуют — их включает `systemctl enable --now` из
    runcmd, до которого исполнение не доходило. И на любой системе не
    доустанавливался qemu-guest-agent, из-за чего панель не узнавала адрес ВМ
    на мосту, а проброс портов вёл в никуда.
    """
    from app.services.cloudinit import WAIT_NETWORK_RUNCMD
    from app.services import marketplace as mp

    # У самой константы есть предел числа итераций
    assert "-le" in WAIT_NETWORK_RUNCMD, "у цикла ожидания сети нет верхней границы"
    assert "i=$((i+1))" in WAIT_NETWORK_RUNCMD, "счётчик итераций не увеличивается"

    def _has_unbounded_wait(text):
        return "while ! ping" in text

    # Сгенерированный cloud-init обычной ВМ и маркетплейса
    from app.api.vms import generate_linux_manifest

    manifest = generate_linux_manifest(FakeReq("rocky", "lamp"), "pw")
    assert not _has_unbounded_wait(_cloudinit_of(manifest)["userData"])

    app = mp.get_app("nextcloud")
    env = mp.add_public_url(mp.resolve_env(app, {}), "10.0.0.5", 28042)
    assert not _has_unbounded_wait(mp.build_marketplace_cloud_init(app, env, "pw"))

    # deployments.py импортом тянет app.db (нужен драйвер БД), поэтому его
    # проверяем по исходнику — здесь важно лишь отсутствие безграничного цикла.
    deployments_src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "deployments.py",
    )
    with open(deployments_src, encoding="utf-8") as f:
        assert not _has_unbounded_wait(f.read())


def test_template_commands_run_after_the_bounded_wait_not_behind_a_hang():
    """Команды шаблона обязаны стоять после ожидания сети (им нужен интернет),
    но само ожидание теперь гарантированно завершается."""
    from app.api.vms import generate_linux_manifest

    userdata = _cloudinit_of(generate_linux_manifest(FakeReq("rocky", "lamp"), "pw"))["userData"]
    wait_at = userdata.index("while [ $i -le 60 ]")
    svc_at = userdata.index("systemctl enable --now httpd")
    assert wait_at < svc_at


# ------------------ брандмауэр гостя и «родные» имена команд -----------------

def test_guest_firewall_is_disabled_only_where_it_ships_enabled():
    """firewalld установлен и активен в RHEL-семействе и openSUSE, и порт 80 в
    разрешённых по умолчанию НЕ значится — только SSH и пара служебных. В
    Debian и Ubuntu брандмауэра по умолчанию нет вовсе.

    Это и оставалось причиной «на Ubuntu сайт открывается, на остальных нет»
    уже после того, как сам шаблон начал отрабатывать: веб-сервер запущен и
    слушает :80, проброс портов с хоста настроен, а firewalld внутри гостя
    молча отбрасывает входящие пакеты. Доступом к ВМ управляет панель на
    уровне хоста, поэтому второй брандмауэр внутри гостя только делает её
    настройки портов неправдой."""
    from app.services.os_profiles import disable_guest_firewall_cmd

    for os_type in ("centos", "rocky", "almalinux", "fedora", "bitrix", "opensuse"):
        assert "firewalld" in disable_guest_firewall_cmd(os_type), os_type
    for os_type in ("ubuntu", "debian", "arch", "alpine"):
        assert disable_guest_firewall_cmd(os_type) == "", os_type


def test_ssh_unit_name_matches_the_family():
    """В Debian/Ubuntu юнит называется ssh, в остальных — sshd. Раньше
    команда всегда пробовала ssh первым, и лог cloud-init на RHEL открывался
    ошибкой «Unit ssh.service not found»."""
    from app.services.os_profiles import restart_ssh_cmd

    assert "restart ssh " in restart_ssh_cmd("ubuntu") + " "
    assert "restart sshd" in restart_ssh_cmd("rocky")
    assert "restart sshd" in restart_ssh_cmd("opensuse")
    # В Alpine нет systemd — там OpenRC
    assert restart_ssh_cmd("alpine").startswith("rc-service")


def test_native_package_manager_comes_first():
    """Иначе каждый лог не-Debian системы начинается с «apt-get: command not
    found» — работает за счёт запасных вариантов, но сбивает с толку при
    разборе проблем."""
    from app.services.os_profiles import install_package_cmd_chain

    assert install_package_cmd_chain("rocky", "qemu-guest-agent").startswith("(dnf install -y")
    assert install_package_cmd_chain("ubuntu", "qemu-guest-agent").startswith("(apt-get update")
    assert install_package_cmd_chain("alpine", "qemu-guest-agent").startswith("(apk add")
    # запасные варианты всё равно присутствуют — на случай неверно определённой ОС
    assert "apt-get" in install_package_cmd_chain("rocky", "qemu-guest-agent")


def test_rhel_manifest_disables_firewalld_before_waiting_for_network():
    """Отключение брандмауэра не должно зависеть от наличия интернета —
    иначе при закрытом ICMP оно ждало бы две минуты впустую."""
    from app.api.vms import generate_linux_manifest

    userdata = _cloudinit_of(generate_linux_manifest(FakeReq("rocky", "lamp"), "pw"))["userData"]
    fw_at = userdata.index("disable --now firewalld")
    wait_at = userdata.index("while [ $i -le 60 ]")
    assert fw_at < wait_at


def test_ubuntu_manifest_has_no_firewalld_line():
    from app.api.vms import generate_linux_manifest

    userdata = _cloudinit_of(generate_linux_manifest(FakeReq("ubuntu", "lamp"), "pw"))["userData"]
    assert "firewalld" not in userdata


# ------------------------- SELinux и порядок шагов ---------------------------

def test_wordpress_on_rhel_restores_selinux_context_after_extracting():
    """Вторая настоящая причина «403 Forbidden» на RHEL-семействе.

    В облачных образах RHEL SELinux работает в режиме enforcing. Файлы,
    распакованные из tar в /var/www/html, получают контекст, отличный от
    httpd_sys_content_t, и Apache отдаёт 403 — при корректных правах доступа
    и запущенной службе, то есть без единого намёка на причину в обычных
    логах."""
    _, commands = build_template_steps("wordpress", "rocky")

    tar_at = next(i for i, c in enumerate(commands) if c.startswith("tar -xzf"))
    restorecon_at = next(i for i, c in enumerate(commands) if "restorecon" in c)
    # Контекст восстанавливаем ПОСЛЕ распаковки — до неё это бессмысленно
    assert tar_at < restorecon_at
    # И до перезапуска веб-сервера
    restart_at = next(i for i, c in enumerate(commands) if "restart httpd" in c)
    assert restorecon_at < restart_at


def test_selinux_commands_are_absent_where_selinux_is_not_used():
    """В Debian и Ubuntu SELinux не используется — лишние команды там только
    засоряли бы лог ошибками."""
    _, commands = build_template_steps("wordpress", "ubuntu")
    assert not any("restorecon" in c for c in commands)
    assert not any("setsebool" in c for c in commands)


def test_wordpress_starts_services_before_touching_the_docroot():
    """Шаблон раскладывает файлы и перезапускает веб-сервер — значит служба
    должна быть уже поднята. Раньше `systemctl restart` шёл РАНЬШЕ, чем
    `systemctl enable --now`, и срабатывало лишь потому, что restart умеет
    запустить остановленную службу."""
    for os_type in ("ubuntu", "rocky"):
        _, commands = build_template_steps("wordpress", os_type)
        enable_at = next(i for i, c in enumerate(commands) if "enable --now" in c)
        wget_at = next(i for i, c in enumerate(commands) if c.startswith("wget"))
        assert enable_at < wget_at, os_type


def test_postgresql_still_initialises_before_starting():
    """Обратная сторона того же порядка: postgresql в RHEL, наоборот, требует
    initdb ДО запуска — без него служба не стартует вообще."""
    _, commands = build_template_steps("postgresql", "rocky")
    initdb_at = next(i for i, c in enumerate(commands) if "initdb" in c)
    start_at = next(i for i, c in enumerate(commands) if "enable --now postgresql" in c)
    assert initdb_at < start_at


# --------------- веб-шаблоны должны отдавать страницу, а не заглушку ---------

def test_web_templates_write_an_index_page():
    """Реальный случай: LEMP на Fedora показывал «Test Page for the HTTP Server
    on Fedora». Стек при этом был поднят — заглушка дистрибутива появляется
    ровно тогда, когда в корне сайта нет ни одного индексного файла. Со стороны
    неотличимо от «шаблон не сработал»."""
    for template in ("lamp", "lemp"):
        for os_type in ("ubuntu", "fedora"):
            _, commands = build_template_steps(template, os_type)
            assert any("index.php" in c for c in commands), (template, os_type)


def test_lemp_wires_nginx_to_php_fpm():
    """nginx сам PHP не исполняет — нужен location с fastcgi_pass, которого
    шаблон LEMP не создавал вообще: ставились nginx и php-fpm, но между собой
    связаны не были."""
    for os_type in ("ubuntu", "fedora", "opensuse"):
        _, commands = build_template_steps("lemp", os_type)
        assert any("fastcgi_pass" in c for c in commands), os_type


def test_php_socket_path_is_pinned_not_guessed_at_runtime():
    """Путь к сокету php-fpm отличается и между дистрибутивами, и между
    версиями PHP (php8.1-fpm.sock, php8.3-fpm.sock…), а на openSUSE пул www
    по умолчанию вообще слушает TCP, а не unix-сокет — искать *.sock рантаймом
    там нечего. Поэтому мы сами прибиваем сокет к фиксированному пути и его же
    прописываем в nginx, вместо угадывания того, что получилось у пакетного
    менеджера."""
    from app.services.os_profiles import AEGIS_PHP_FPM_SOCK

    for os_type in ("ubuntu", "fedora", "opensuse"):
        _, commands = build_template_steps("lemp", os_type)
        pin_cmd = next(c for c in commands if "sed -i" in c and "listen" in c)
        conf_cmd = next(c for c in commands if "fastcgi_pass" in c)
        assert AEGIS_PHP_FPM_SOCK in pin_cmd, os_type
        assert f"fastcgi_pass unix:{AEGIS_PHP_FPM_SOCK}" in conf_cmd, os_type
        # А переменные nginx, наоборот, обязаны дойти до конфига неразвёрнутыми
        assert "$document_root" in conf_cmd, os_type


def test_opensuse_php_packages_are_not_in_the_atomic_packages_list():
    """php8/php8-fpm нет в стандартном OSS-репозитории Leap 15.6 — если их
    оставить в декларативном "packages", cloud-init поставит все пакеты одной
    транзакцией zypper, и одно нерезолвящееся имя провалит всю транзакцию,
    утащив за собой даже nginx/apache2/mariadb, которые в стандартном
    репозитории есть. Поэтому php-пакеты suse обязаны ставиться отдельной
    командой после подключения репозитория, а не сидеть в packages."""
    for template in ("lamp", "lemp"):
        packages, commands = build_template_steps(template, "opensuse")
        assert not any("php" in p for p in packages), (template, packages)
        assert any("php8" in c and "install" in c for c in commands), template


def test_opensuse_registers_the_php_repo_before_installing_php():
    """devel:languages:php должен быть подключён раньше, чем zypper install
    php8* — иначе ставить будет неоткуда."""
    for template in ("lamp", "lemp"):
        _, commands = build_template_steps(template, "opensuse")
        repo_idx = next(i for i, c in enumerate(commands) if "zypper" in c and " ar " in c)
        install_idx = next(
            i for i, c in enumerate(commands) if "zypper" in c and "install php8" in c
        )
        assert repo_idx < install_idx, template


def test_web_root_differs_between_apache_and_nginx_on_rhel():
    """В RHEL-семействе Apache отдаёт /var/www/html, а nginx —
    /usr/share/nginx/html. Страница, положенная не туда, просто не отдаётся."""
    from app.services.os_profiles import APACHE_ROOT, NGINX_ROOT

    assert APACHE_ROOT["rhel"] == "/var/www/html"
    assert NGINX_ROOT["rhel"] == "/usr/share/nginx/html"

    _, lamp = build_template_steps("lamp", "fedora")
    _, lemp = build_template_steps("lemp", "fedora")
    assert any("/var/www/html/index.php" in c for c in lamp)
    assert any("/usr/share/nginx/html/index.php" in c for c in lemp)


def test_nginx_config_is_validated_before_reload():
    """Битый конфиг не должен ронять уже работающий nginx — сначала nginx -t."""
    for os_type in ("ubuntu", "fedora", "opensuse"):
        _, commands = build_template_steps("lemp", os_type)
        reload_cmd = next(c for c in commands if "reload nginx" in c)
        assert reload_cmd.startswith("nginx -t &&"), os_type


def test_php_fpm_unit_name_is_not_left_to_shell_globbing():
    """`systemctl enable --now php*-fpm` не делает то, что кажется: bash
    пытается развернуть маску по файлам текущего каталога, а не по юнитам
    systemd, и в Debian/Ubuntu юнит версионирован (php8.3-fpm.service) и
    меняется от релиза к релизу. Маска должна уходить в
    `systemctl list-unit-files`, который матчит её сам."""
    _, commands = build_template_steps("lemp", "ubuntu")
    enable_cmd = next(c for c in commands if "enable --now" in c and "php" in c)
    assert "list-unit-files" in enable_cmd
    assert "'php*-fpm.service'" in enable_cmd


def test_redis_on_fedora_also_tries_the_valkey_unit():
    """Fedora 41+ заменила Redis на Valkey (Redis сменил лицензию на SSPL).
    `dnf install redis` ставит valkey-compat: redis-cli/redis-server на
    месте, но ЮНИТ называется valkey.service — прежний
    `systemctl enable --now redis` там не запускал ничего."""
    _, commands = build_template_steps("redis", "fedora")
    start = " ".join(commands)
    assert "redis" in start and "valkey" in start
    # На AlmaLinux/Rocky юнит по-прежнему redis — он должен идти первым
    assert start.index("--now redis") < start.index("--now valkey")


def test_redis_on_opensuse_creates_a_config_and_uses_the_templated_unit():
    """В openSUSE redis собран на шаблонных юнитах (redis@<экземпляр>) и без
    конфига не стартует вовсе."""
    _, commands = build_template_steps("redis", "opensuse")
    blob = " ".join(commands)
    assert "default.conf.example" in blob, "конфиг из примера не создаётся"
    assert "redis@default" in blob, "шаблонный юнит не используется"


def test_redis_config_is_not_overwritten_if_it_already_exists():
    """Иначе перезапуск шаблона затирал бы правки пользователя."""
    _, commands = build_template_steps("redis", "opensuse")
    copy_cmd = next(c for c in commands if "default.conf.example" in c)
    assert copy_cmd.startswith("[ -f ")


def test_redis_still_uses_the_plain_unit_where_that_is_correct():
    for os_type, expected in (("ubuntu", "redis-server"), ("arch", "redis")):
        _, commands = build_template_steps("redis", os_type)
        assert any(f"--now {expected}" in c for c in commands), os_type


def test_redis_on_alpine_uses_openrc():
    _, commands = build_template_steps("redis", "alpine")
    assert any("rc-update" in c for c in commands)
    assert not any("systemctl" in c for c in commands)


def test_optional_packages_never_share_a_transaction_with_required_ones_on_suse():
    """cloud-init ставит весь список packages ОДНОЙ транзакцией zypper: одно
    неразрешимое имя проваливает её целиком, вместе с обязательными пакетами.
    Так уже ломался LAMP на openSUSE (php8 нет в стандартном репозитории Leap),
    и ВМ поднималась вообще без веб-сервера.

    Поэтому всё, чего может не оказаться в конкретном релизе Leap, ставится
    отдельной необязательной командой, а не декларативно."""
    docker_pkgs, docker_cmds = build_template_steps("docker", "opensuse")
    assert "docker" in docker_pkgs, "сам docker обязателен и остаётся в packages"
    assert "docker-compose" not in docker_pkgs, (
        "docker-compose есть не в каждом релизе Leap — в атомарном списке он "
        "утащил бы за собой docker"
    )
    compose = next(c for c in docker_cmds if "docker-compose" in c)
    assert compose.rstrip().endswith("|| true"), "установка compose должна быть необязательной"


def test_docker_itself_still_starts_on_suse():
    _, commands = build_template_steps("docker", "opensuse")
    assert any("enable --now docker" in c for c in commands)


def test_portainer_inherits_the_suse_docker_fix():
    _, commands = build_template_steps("portainer", "opensuse")
    assert any("docker-compose" in c and c.rstrip().endswith("|| true") for c in commands)
    assert any("portainer/portainer-ce" in c for c in commands)


def test_no_suse_template_keeps_php_in_the_atomic_package_list():
    """Общая формулировка того же правила для php — оно и было первым случаем."""
    for template in ("lamp", "lemp"):
        packages, _ = build_template_steps(template, "opensuse")
        assert not any("php" in p for p in packages), (template, packages)


# ------------------------------- Zabbix -------------------------------------

def test_zabbix_is_offered_only_where_official_packages_exist():
    """Zabbix ставится из репозитория Zabbix SIA, собранного под конкретные
    релизы. Debian/Ubuntu и RHEL-семейство там есть; Arch, Alpine и openSUSE —
    нет (у openSUSE только сборка сообщества, не от Zabbix SIA)."""
    for os_type in ("ubuntu", "debian", "almalinux", "rocky", "centos"):
        assert template_supported("zabbix", os_type) is True, os_type
    for os_type in ("arch", "alpine", "opensuse"):
        assert template_supported("zabbix", os_type) is False, os_type


def test_zabbix_is_not_offered_on_fedora():
    """У Fedora VERSION_ID вида «41», а репозитория el41 не существует — адрес
    собирается в госте из VERSION_ID и для неё сломался бы принципиально.
    Своих пакетов Zabbix в репозиториях Fedora тоже нет."""
    assert template_supported("zabbix", "fedora") is False
    assert "zabbix" not in supported_templates_for("fedora")
    # но остальные шаблоны у Fedora остаются
    assert "docker" in supported_templates_for("fedora")


def test_zabbix_is_blocked_on_bitrix_like_other_web_stacks():
    """Zabbix поднимает свой Apache на порту 80 — рядом с собственным стеком
    Bitrix это тот же конфликт, что у LAMP."""
    from app.services.os_profiles import WEB_STACK_TEMPLATES

    assert "zabbix" in WEB_STACK_TEMPLATES
    assert template_supported("zabbix", "bitrix") is False


def test_zabbix_repo_url_is_built_from_os_release_not_hardcoded():
    """Репозиторий Zabbix собран под конкретные релизы (ubuntu24.04, debian12,
    rhel/9). Зашить один адрес нельзя — он верен максимум для одной ОС."""
    _, deb = build_template_steps("zabbix", "ubuntu")
    repo = next(c for c in deb if "repo.zabbix.com" in c)
    assert "/etc/os-release" in repo
    assert "${ID}" in repo and "${VERSION_ID}" in repo

    _, rhel = build_template_steps("zabbix", "almalinux")
    repo = next(c for c in rhel if "repo.zabbix.com" in c)
    # У AlmaLinux VERSION_ID бывает «9.4» — репозиторию нужен мажорный номер
    assert "${VERSION_ID%%.*}" in repo


def test_zabbix_packages_are_installed_after_the_repo_is_registered():
    """Пакеты Zabbix есть только во внешнем репозитории. В декларативном
    packages они провалили бы всю транзакцию — как php8 на openSUSE."""
    for os_type in ("ubuntu", "almalinux"):
        packages, commands = build_template_steps("zabbix", os_type)
        assert not any("zabbix" in p for p in packages), (os_type, packages)
        repo_at = next(i for i, c in enumerate(commands) if "repo.zabbix.com" in c)
        install_at = next(i for i, c in enumerate(commands)
                          if "zabbix-server-mysql" in c and "install" in c)
        assert repo_at < install_at, os_type


def test_zabbix_skips_the_web_setup_wizard():
    """Готовый zabbix.conf.php — именно он отменяет веб-мастер установки,
    иначе после разворачивания пришлось бы вручную проходить его в браузере."""
    for os_type in ("ubuntu", "almalinux"):
        _, commands = build_template_steps("zabbix", os_type)
        conf = next(c for c in commands
                    if "/etc/zabbix/web/zabbix.conf.php" in c and "printf" in c)
        assert '$DB["TYPE"] = "MYSQL"' in conf, os_type
        assert '$DB["DATABASE"] = "zabbix"' in conf, os_type


def test_zabbix_db_password_is_generated_in_the_guest_and_reused():
    """Пароль генерируется в госте (в статическом шаблоне его взять неоткуда)
    и должен попасть в ТРИ места: пользователя БД, zabbix_server.conf и конфиг
    фронтенда. Каждая команда runcmd — отдельный процесс, поэтому переменные
    между ними не живут и пароль читается из файла."""
    from app.services.os_profiles import ZABBIX_DB_PASS_FILE

    _, commands = build_template_steps("zabbix", "ubuntu")
    gen = next(c for c in commands if "openssl rand" in c)
    # Файл создаётся сразу с правами 600, а не chmod после записи
    assert f"install -m 600 /dev/null {ZABBIX_DB_PASS_FILE}" in gen

    users = [c for c in commands if f"cat {ZABBIX_DB_PASS_FILE}" in c]
    assert any("identified by" in c for c in users), "пароль не заводится в БД"
    assert any("zabbix_server.conf" in c for c in users), "пароля нет в конфиге сервера"
    assert any("zabbix.conf.php" in c for c in users), "пароля нет в конфиге фронтенда"


def test_zabbix_imports_the_schema_before_starting_the_server():
    """zabbix-server на пустой базе не стартует — схема должна быть залита
    раньше."""
    _, commands = build_template_steps("zabbix", "ubuntu")
    schema_at = next(i for i, c in enumerate(commands) if "server.sql.gz" in c)
    start_at = next(i for i, c in enumerate(commands) if "enable --now zabbix-server" in c)
    assert schema_at < start_at


def test_zabbix_installs_command_line_tools():
    """zabbix_get и zabbix_sender — управление из терминала панели без браузера."""
    for os_type in ("ubuntu", "almalinux"):
        _, commands = build_template_steps("zabbix", os_type)
        install = next(c for c in commands if "zabbix-server-mysql" in c and "install" in c)
        assert "zabbix-get" in install and "zabbix-sender" in install, os_type


def test_zabbix_uses_the_right_web_user_per_family():
    """В Debian веб-сервер работает от www-data, в RHEL — от apache."""
    _, deb = build_template_steps("zabbix", "ubuntu")
    _, rhel = build_template_steps("zabbix", "almalinux")
    assert any("chown www-data:www-data" in c for c in deb)
    assert any("chown apache:apache" in c for c in rhel)
    assert any("apache2" in c for c in deb)
    assert any("httpd" in c for c in rhel)


def test_zabbix_handles_selinux_only_on_rhel():
    """В облачных образах RHEL SELinux в режиме enforcing: без булевых
    веб-интерфейс не достучится до базы и до zabbix-server."""
    _, rhel = build_template_steps("zabbix", "almalinux")
    assert any("httpd_can_connect_zabbix" in c for c in rhel)
    _, deb = build_template_steps("zabbix", "ubuntu")
    assert not any("setsebool" in c for c in deb)


def test_zabbix_points_email_at_the_panel_mail_server():
    """Иначе оповещения слать некуда: штатный канал приезжает выключенным и с
    заглушкой mail.example.com. Сетевой путь открыт (SMTP не в списке
    заблокированных для ВМ портов), не хватает только настройки."""
    from app.services.os_profiles import AEGIS_BRIDGE_GATEWAY

    for os_type in ("ubuntu", "almalinux"):
        _, commands = build_template_steps("zabbix", os_type)
        sql = next(c for c in commands if "media_type" in c)
        assert f"smtp_server='{AEGIS_BRIDGE_GATEWAY}'" in sql, os_type
        assert "status=0" in sql, "канал должен включаться, иначе он бесполезен"


def test_zabbix_mail_setup_does_not_touch_gmail_or_office365():
    """Zabbix поставляет и Gmail/Office365 с НАСТОЯЩИМИ серверами. Условие
    должно попадать ровно в штатные Email/Email (HTML), которые идут с
    заглушкой, иначе мы перенастроим и чужие каналы."""
    _, commands = build_template_steps("zabbix", "ubuntu")
    sql = next(c for c in commands if "media_type" in c)
    assert "smtp_server='mail.example.com'" in sql, "нет условия по заглушке"
    assert "type=0" in sql, "нет ограничения по типу «почта»"


def test_zabbix_configures_mail_after_the_schema_exists():
    """Таблица media_type появляется только вместе со схемой."""
    _, commands = build_template_steps("zabbix", "ubuntu")
    schema_at = next(i for i, c in enumerate(commands) if "server.sql.gz" in c)
    mail_at = next(i for i, c in enumerate(commands) if "media_type" in c)
    assert schema_at < mail_at
