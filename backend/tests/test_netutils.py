from app.core.netutils import is_internal_ip, pick_external_ip


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
