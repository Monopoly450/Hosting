from app.core.netutils import (
    is_internal_ip,
    pick_external_ip,
    is_valid_ipv4,
    is_valid_ip_or_cidr,
    is_safe_name,
)


def test_internal_prefixes():
    assert is_internal_ip("10.244.0.5")
    assert is_internal_ip("10.42.1.2")
    assert is_internal_ip("10.0.2.2")
    assert is_internal_ip("127.0.0.1")
    assert is_internal_ip("fe80::1")   # IPv6
    assert is_internal_ip("")


def test_external_ip_not_internal():
    assert not is_internal_ip("172.20.0.55")
    assert not is_internal_ip("203.0.113.10")
    assert not is_internal_ip("192.168.1.50")


def test_pick_prefers_external():
    ips = ["10.0.2.2", "10.244.0.7", "172.20.0.55"]
    assert pick_external_ip(ips) == "172.20.0.55"


def test_pick_falls_back_to_internal_ipv4_when_no_external():
    ips = ["fe80::1", "10.42.0.9"]
    assert pick_external_ip(ips) == "10.42.0.9"


def test_pick_empty():
    assert pick_external_ip([]) is None
    assert pick_external_ip(None) is None


def test_consistency_between_helpers():
    # Адрес, выбранный pick_external_ip, не должен быть внутренним, если есть внешний
    assert not is_internal_ip(pick_external_ip(["10.244.0.1", "172.20.0.99"]))


# --- Валидаторы против инъекций ---

def test_valid_ipv4():
    assert is_valid_ipv4("192.168.1.1")
    assert is_valid_ipv4("10.0.0.255")
    assert not is_valid_ipv4("256.1.1.1")
    assert not is_valid_ipv4("1.2.3")
    assert not is_valid_ipv4("1.2.3.4.5")


def test_ipv4_rejects_injection():
    # Ключевая защита: строки с shell-метасимволами не проходят валидацию
    assert not is_valid_ipv4("8.8.8.8; rm -rf /")
    assert not is_valid_ipv4("8.8.8.8 -j ACCEPT")
    assert not is_valid_ipv4("$(id)")
    assert not is_valid_ipv4("")


def test_valid_ip_or_cidr():
    assert is_valid_ip_or_cidr("10.0.0.0/8")
    assert is_valid_ip_or_cidr("192.168.1.5")
    assert not is_valid_ip_or_cidr("10.0.0.0/33")
    assert not is_valid_ip_or_cidr("10.0.0.0/8; reboot")
    assert not is_valid_ip_or_cidr("0.0.0.0/0 -j DROP")


def test_safe_name():
    assert is_safe_name("web-01")
    assert is_safe_name("pool123")
    assert not is_safe_name("../etc/passwd")
    assert not is_safe_name("a; rm -rf /")
    assert not is_safe_name("Name_With_Underscore")
    assert not is_safe_name("")
