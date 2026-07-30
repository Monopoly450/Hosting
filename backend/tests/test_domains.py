import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import domains as d


# ------------------------------ Валидация -----------------------------------

def test_valid_domains():
    for name in ("example.com", "app.example.com", "a-b.example.co.uk", "x1.test.io"):
        assert d.is_valid_domain(name), name


def test_invalid_domains():
    for name in ("", "localhost", "no-tld", "-bad.example.com", "bad-.example.com",
                 "sp ace.com", "a" * 64 + ".com", "точка.рф "):
        assert not d.is_valid_domain(name), name


# ---------------------------- Генерация конфига -----------------------------

def test_caddyfile_has_site_block_per_domain():
    cfg = d.build_caddyfile([
        {"domain": "b.example.com", "upstream": "192.168.100.12:2368"},
        {"domain": "a.example.com", "upstream": "192.168.100.11:8080"},
    ])
    assert "a.example.com {" in cfg
    assert "b.example.com {" in cfg
    assert "reverse_proxy 192.168.100.11:8080" in cfg
    assert "reverse_proxy 192.168.100.12:2368" in cfg
    # домены отсортированы — конфиг стабилен между перегенерациями
    assert cfg.index("a.example.com") < cfg.index("b.example.com")


def test_caddyfile_includes_acme_email_when_set():
    cfg = d.build_caddyfile([{"domain": "a.example.com", "upstream": "1.2.3.4:80"}], email="me@example.com")
    assert "email me@example.com" in cfg


def test_caddyfile_without_email_has_no_global_block():
    cfg = d.build_caddyfile([{"domain": "a.example.com", "upstream": "1.2.3.4:80"}])
    assert "email" not in cfg


def test_caddyfile_empty_is_still_valid_config():
    """Пустой Caddyfile невалиден для Caddy — должна быть заглушка,
    иначе контейнер не поднимется, когда доменов ещё нет."""
    cfg = d.build_caddyfile([])
    assert cfg.strip()
    assert "respond" in cfg


# ------------------------------- DNS-проверка -------------------------------

def test_check_dns_match(monkeypatch):
    monkeypatch.setattr(d.socket, "gethostbyname", lambda h: "10.0.0.5")
    ok, detail = d.check_dns("app.example.com", "10.0.0.5")
    assert ok is True and detail == "10.0.0.5"


def test_check_dns_mismatch(monkeypatch):
    monkeypatch.setattr(d.socket, "gethostbyname", lambda h: "1.2.3.4")
    ok, detail = d.check_dns("app.example.com", "10.0.0.5")
    assert ok is False
    assert "1.2.3.4" in detail and "10.0.0.5" in detail


def test_check_dns_unresolvable(monkeypatch):
    def boom(h):
        raise OSError("NXDOMAIN")
    monkeypatch.setattr(d.socket, "gethostbyname", boom)
    ok, detail = d.check_dns("nope.example.com", "10.0.0.5")
    assert ok is False and "не резолвится" in detail


# ------------------------------ Статус Caddy --------------------------------

def test_caddy_status_without_docker():
    class NoDocker:
        def is_available(self): return False
    st = d.caddy_status(NoDocker())
    assert st["docker"] is False and st["running"] is False
    assert "host_ip" in st


def test_caddyfile_tar_roundtrip():
    """Конфиг кладём в контейнер через tar — проверяем, что архив читается."""
    import tarfile
    buf = d._caddyfile_tar("hello { }")
    with tarfile.open(fileobj=buf, mode="r") as tar:
        member = tar.getmember("Caddyfile")
        assert tar.extractfile(member).read().decode() == "hello { }"


# ---------------------- публичность адреса хоста ----------------------------

@pytest.mark.parametrize("ip", [
    "192.168.31.10",   # адрес из скриншота: сервер в локальной сети
    "192.168.1.1",
    "10.0.0.5",
    "172.16.0.10",
    "172.31.255.254",
    "127.0.0.1",
    "169.254.169.254",
])
def test_private_addresses_detected(ip):
    """Let's Encrypt стучится на порт 80 ИЗВНЕ: на такой адрес сертификат
    не выпустится, и предупредить нужно до правки DNS."""
    assert d.is_private_host_ip(ip) is True


@pytest.mark.parametrize("ip", ["185.177.219.140", "8.8.8.8", "1.1.1.1"])
def test_public_addresses_pass(ip):
    assert d.is_private_host_ip(ip) is False


@pytest.mark.parametrize("ip", ["203.0.113.10", "198.51.100.7"])
def test_documentation_ranges_also_unreachable(ip):
    """Адреса из RFC 5737 (примеры в документации) не маршрутизируются —
    сертификат на них тоже не выпустится."""
    assert d.is_private_host_ip(ip) is True


def test_garbage_value_is_not_reported_as_private():
    """Имя хоста вместо адреса не должно выдавать ложное предупреждение."""
    assert d.is_private_host_ip("host.example.com") is False


def test_status_reports_whether_host_is_reachable(monkeypatch):
    monkeypatch.setenv("AEGIS_HOST_IP", "192.168.31.10")

    class NoDocker:
        def is_available(self): return False

    st = d.caddy_status(NoDocker())
    assert st["host_ip"] == "192.168.31.10"
    assert st["host_ip_is_private"] is True
