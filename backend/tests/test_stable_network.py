"""Регрессионные тесты для сети ВМ на мосту br-vms.

Раньше маркетплейс и деплой из GitHub писали в cloud-init собственный
netplan с dhcp4 на ВСЕ "e*"-интерфейсы вместо статического адреса на
мостовом интерфейсе — второй (br-vms) интерфейс получал случайную аренду
DHCP вместо детерминированного 172.20.0.<30+id%200>, из-за чего адрес
«плавал» между перезагрузками, а в редких случаях мог совпасть с чужой
статической ВМ. Плюс — установка qemu-guest-agent (единственный канал, по
которому KubeVirt узнаёт IP мостового интерфейса) была одной попыткой без
повтора, в отличие от обычных ВМ.
"""
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from app.services.cloudinit import build_network_data, GUEST_AGENT_RETRY_RUNCMD
from app.services import marketplace as mp

POD_MAC = "02:00:00:11:22:33"
LAN_MAC = "02:00:00:44:55:66"


def test_static_ip_pins_bridge_interface_by_mac():
    nd = yaml.safe_load(build_network_data(POD_MAC, LAN_MAC, "172.20.0.130"))
    assert nd["version"] == 2
    stable = nd["ethernets"]["stable-nic"]
    assert stable["match"]["macaddress"] == LAN_MAC
    assert stable["dhcp4"] is False
    assert stable["addresses"] == ["172.20.0.130/24"]
    # pod-интерфейс всегда DHCP — интернет/сеть кластера
    pod = nd["ethernets"]["pod-nic"]
    assert pod["match"]["macaddress"] == POD_MAC
    assert pod["dhcp4"] is True


def test_without_static_ip_bridge_falls_back_to_dhcp():
    nd = yaml.safe_load(build_network_data(POD_MAC, LAN_MAC, None))
    assert nd["ethernets"]["stable-nic"]["dhcp4"] is True
    assert "addresses" not in nd["ethernets"]["stable-nic"]


def test_guest_agent_install_covers_every_package_manager():
    # Регрессия 1: раньше была ОДНА попытка apt-get без повтора — единственная
    # транзиентная неудача (занятый dpkg-лок сразу после загрузки) навсегда
    # лишала ВМ видимого мостового IP, т.к. агент никто не переустанавливал.
    assert "while" in GUEST_AGENT_RETRY_RUNCMD
    assert "sleep 5" in GUEST_AGENT_RETRY_RUNCMD
    # Регрессия 2: перебирались только apt/dnf/yum, поэтому на openSUSE, Arch
    # и Alpine агент не ставился вообще и адрес мостового интерфейса не
    # становился известен панели никогда.
    for pm in ("apt-get", "dnf", "yum", "zypper", "pacman", "apk"):
        assert pm in GUEST_AGENT_RETRY_RUNCMD, pm
    # В Alpine нет systemd — нужен запасной путь через OpenRC
    assert "rc-update add qemu-guest-agent" in GUEST_AGENT_RETRY_RUNCMD


def test_marketplace_cloud_init_no_longer_configures_network():
    """Сеть задаётся networkData в манифесте, а не файлом netplan в cloud-init.

    netplan есть только в Ubuntu; когда каждый сборщик писал свой файл, их
    приходилось держать синхронными вручную, и любое расхождение возвращало
    «плавающий» адрес на мосту."""
    app = mp.get_app("nextcloud")
    env = mp.add_public_url(mp.resolve_env(app, {}), "192.168.31.10", 28014)
    ci = mp.build_marketplace_cloud_init(app, env, "pw")
    doc = yaml.safe_load(ci)
    files = {f["path"]: f["content"] for f in doc["write_files"]}
    assert "/etc/netplan/99-dhcp.yaml" not in files
    assert "netplan apply" not in ci
    # Compose и .env по-прежнему на месте
    assert "/opt/app/docker-compose.yml" in files
    assert "/opt/app/.env" in files


def test_ip_rule_matching_does_not_hit_other_vms_by_substring():
    """Реальный баг: голое `vm_ip in line` считало 172.20.0.13 совпавшим с
    правилом для 172.20.0.130 (один просто префикс другого). При каждой смене
    IP какой-нибудь ВМ это могло стереть DNAT/FORWARD правило совсем другой
    машины, у которой адрес не менялся — сайты переставали открываться, а SSH
    отваливался без видимой причины."""
    from app.api.vms import _ip_in_rule

    assert not _ip_in_rule(
        "172.20.0.13",
        "-A PREROUTING -p tcp --dport 28014 -j DNAT --to-destination 172.20.0.130:80",
    )
    assert _ip_in_rule(
        "172.20.0.13",
        "-A PREROUTING -p tcp --dport 22013 -j DNAT --to-destination 172.20.0.13:22",
    )
    assert _ip_in_rule("172.20.0.13", "-A FORWARD -p tcp -d 172.20.0.13/32 --dport 80 -j ACCEPT")
    assert not _ip_in_rule("20.0.13", "-A FORWARD -p tcp -d 172.20.0.130 --dport 80 -j ACCEPT")


def test_resolve_vm_ip_matches_pick_external_ip():
    """vms.resolve_vm_ip раньше был отдельной копией той же фильтрации и не
    знал про 192.168.100.x (сеть изоляции кластеров) — SSH/терминал ВМ в
    кластере мог получить как «внешний» адрес изоляции вместо настоящего
    маршрутизируемого с хоста IP. Теперь это алиас pick_external_ip."""
    from app.api.vms import resolve_vm_ip
    from app.core.netutils import pick_external_ip

    cases = [
        ["10.244.0.1", "192.168.100.5", "172.20.0.99"],
        ["192.168.100.5", "10.42.0.9"],
        ["192.168.100.5"],
        [],
    ]
    for ips in cases:
        assert resolve_vm_ip(ips) == pick_external_ip(ips)
    assert resolve_vm_ip(["192.168.100.5", "10.42.0.9"]) == "10.42.0.9"
