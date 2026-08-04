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


def test_every_general_purpose_os_supports_at_least_one_template():
    from app.services.os_profiles import SELF_CONTAINED_OS

    for os_type in _all_linux_os_types():
        if os_type in SELF_CONTAINED_OS:
            continue
        assert supported_templates_for(os_type), os_type


def test_bitrix_takes_no_templates_because_it_is_already_a_stack():
    """Реальный случай: Bitrix + LAMP отдавал «403 Forbidden от nginx/1.21.5».

    bitrix-env.sh разворачивает собственный полный стек — nginx впереди,
    за ним Apache, MySQL и PHP. Шаблон LAMP ставил поверх ещё один Apache,
    оба стека делили порт 80, выигрывал nginx от Bitrix и отдавал 403,
    потому что сайт в нём ещё не настроен."""
    from app.services.os_profiles import SELF_CONTAINED_OS

    assert "bitrix" in SELF_CONTAINED_OS
    assert supported_templates_for("bitrix") == []
    for template in ("lamp", "lemp", "wordpress", "docker", "redis"):
        assert template_supported(template, "bitrix") is False, template
    # ВМ без шаблона на Bitrix по-прежнему создаётся — это штатный сценарий
    assert template_supported("", "bitrix") is True


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
