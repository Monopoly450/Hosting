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

from app.services.cloudinit import build_stable_netplan_yaml, GUEST_AGENT_RETRY_RUNCMD
from app.services import marketplace as mp

POD_MAC = "02:00:00:11:22:33"
LAN_MAC = "02:00:00:44:55:66"


def _parse_netplan(yaml_block: str) -> dict:
    return yaml.safe_load(yaml_block)


def test_static_ip_pins_bridge_interface_by_mac():
    netplan = _parse_netplan(build_stable_netplan_yaml(POD_MAC, LAN_MAC, "172.20.0.130"))
    stable = netplan["network"]["ethernets"]["stable-nic"]
    assert stable["match"]["macaddress"] == LAN_MAC
    assert stable["dhcp4"] is False
    assert stable["addresses"] == ["172.20.0.130/24"]
    # pod-интерфейс всегда DHCP — интернет/сеть кластера
    pod = netplan["network"]["ethernets"]["pod-nic"]
    assert pod["match"]["macaddress"] == POD_MAC
    assert pod["dhcp4"] is True


def test_without_static_ip_bridge_falls_back_to_dhcp():
    netplan = _parse_netplan(build_stable_netplan_yaml(POD_MAC, LAN_MAC, None))
    assert netplan["network"]["ethernets"]["stable-nic"]["dhcp4"] is True
    assert "addresses" not in netplan["network"]["ethernets"]["stable-nic"]


def test_guest_agent_install_retries_instead_of_one_shot():
    # Регрессия: маркетплейс/деплой раньше делали ОДНУ попытку apt-get без
    # повтора — единственная транзиентная неудача (занятый dpkg-лок сразу
    # после загрузки и т.п.) навсегда лишала ВМ видимого мостового IP.
    assert "while" in GUEST_AGENT_RETRY_RUNCMD
    assert "sleep 5" in GUEST_AGENT_RETRY_RUNCMD
    assert "systemctl enable --now qemu-guest-agent" in GUEST_AGENT_RETRY_RUNCMD


def test_marketplace_cloud_init_uses_static_bridge_ip_when_given():
    app = mp.get_app("nextcloud")
    env = mp.add_public_url(mp.resolve_env(app, {}), "192.168.31.10", 28014)
    ci = mp.build_marketplace_cloud_init(
        app, env, "pw", pod_mac=POD_MAC, lan_mac=LAN_MAC, static_ip="172.20.0.130"
    )
    doc = yaml.safe_load(ci)
    files = {f["path"]: f["content"] for f in doc["write_files"]}
    netplan = yaml.safe_load(files["/etc/netplan/99-dhcp.yaml"])
    stable = netplan["network"]["ethernets"]["stable-nic"]
    assert stable["dhcp4"] is False
    assert stable["addresses"] == ["172.20.0.130/24"]
    # Установка guest-agent теперь с повтором, не единственной попыткой
    assert "while" in ci and "qemu-guest-agent" in ci


def test_marketplace_cloud_init_without_macs_keeps_old_behavior():
    """Обратная совместимость: без MAC-адресов поведение как раньше (общий
    dhcp4 на все "e*"), чтобы вызов без новых аргументов не ломался."""
    app = mp.get_app("ghost")
    env = mp.add_public_url(mp.resolve_env(app, {}), "192.168.31.10", 28014)
    ci = mp.build_marketplace_cloud_init(app, env, "pw")
    doc = yaml.safe_load(ci)
    files = {f["path"]: f["content"] for f in doc["write_files"]}
    netplan = yaml.safe_load(files["/etc/netplan/99-dhcp.yaml"])
    assert netplan["network"]["ethernets"]["all-eth"]["dhcp4"] is True


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
