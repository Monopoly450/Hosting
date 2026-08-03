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
