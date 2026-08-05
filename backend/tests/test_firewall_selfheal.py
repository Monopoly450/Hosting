"""Проброс портов должен восстанавливаться сам, а не только при смене IP."""
from app.api.vms import dnat_rules_present, resolve_vm_ports

# Настоящий формат вывода `iptables -t nat -S PREROUTING`
PREROUTING_OK = """-P PREROUTING ACCEPT
-A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER
-A PREROUTING -p tcp -m tcp --dport 22007 -j DNAT --to-destination 172.20.0.14:22
-A PREROUTING -p tcp -m tcp --dport 28007 -j DNAT --to-destination 172.20.0.14:80
-A PREROUTING -p tcp -m tcp --dport 44307 -j DNAT --to-destination 172.20.0.14:443
"""

# То же самое после того, как Docker переписал iptables: наши правила ушли
PREROUTING_WIPED = """-P PREROUTING ACCEPT
-A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER
"""

PORTS = [
    {"ext_port": 22007, "int_port": 22, "name": "SSH"},
    {"ext_port": 28007, "int_port": 80, "name": "HTTP"},
    {"ext_port": 44307, "int_port": 443, "name": "HTTPS"},
]


def test_present_rules_are_recognised():
    assert dnat_rules_present(PREROUTING_OK, "172.20.0.14", PORTS)


def test_wiped_rules_are_detected():
    """Именно этот случай раньше не ловился: IP не менялся, поэтому демон
    считал, что всё применено, и проброс оставался сломанным."""
    assert not dnat_rules_present(PREROUTING_WIPED, "172.20.0.14", PORTS)


def test_partially_wiped_rules_are_detected():
    partial = "\n".join(PREROUTING_OK.splitlines()[:3]) + "\n"
    assert not dnat_rules_present(partial, "172.20.0.14", PORTS)


def test_rules_pointing_at_another_vm_do_not_count():
    """Правила есть, но ведут на другой адрес — для нашей ВМ это отсутствие."""
    assert not dnat_rules_present(PREROUTING_OK, "172.20.0.99", PORTS)


def test_similar_ip_does_not_count_as_a_match():
    """172.20.0.1 — подстрока 172.20.0.14, но это разные машины."""
    assert not dnat_rules_present(PREROUTING_OK, "172.20.0.1", PORTS)


def test_similar_port_does_not_count_as_a_match():
    """--dport 2200 не должен совпасть с правилом для 22007."""
    ports = [{"ext_port": 2200, "int_port": 22, "name": "SSH"}]
    assert not dnat_rules_present(PREROUTING_OK, "172.20.0.14", ports)


def test_port_list_matches_what_reconcile_would_apply():
    """Проверка и применение обязаны считать порты одинаково, иначе вотчдог
    переустанавливал бы правила в каждом цикле."""
    ports = resolve_vm_ports("172.20.0.14", vm_id=7, ports_config=None, os_type="ubuntu")
    assert [p["ext_port"] for p in ports] == [22007, 28007, 44307]
    assert dnat_rules_present(PREROUTING_OK, "172.20.0.14", ports)


def test_explicit_ports_config_wins_over_defaults():
    ports = resolve_vm_ports("172.20.0.14", vm_id=7,
                             ports_config='[{"ext_port": 9000, "int_port": 90}]',
                             os_type="ubuntu")
    assert ports == [{"ext_port": 9000, "int_port": 90}]


def test_windows_gets_rdp():
    ports = resolve_vm_ports("172.20.0.14", vm_id=7, ports_config=None, os_type="windows")
    assert 3389 in [p["int_port"] for p in ports]
