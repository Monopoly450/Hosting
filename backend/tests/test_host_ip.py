import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import netutils


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("AEGIS_HOST_IP", "203.0.113.10")
    assert netutils.detect_host_ip() == "203.0.113.10"


def test_host_ip_alias_supported(monkeypatch):
    monkeypatch.delenv("AEGIS_HOST_IP", raising=False)
    monkeypatch.setenv("HOST_IP", "198.51.100.7")
    assert netutils.detect_host_ip() == "198.51.100.7"


def test_env_value_is_trimmed(monkeypatch):
    monkeypatch.setenv("AEGIS_HOST_IP", "  203.0.113.10  ")
    assert netutils.detect_host_ip() == "203.0.113.10"


def test_empty_env_falls_through_to_autodetect(monkeypatch):
    """docker-compose передаёт AEGIS_HOST_IP= (пустым), если он не задан —
    пустая строка не должна становиться «адресом»."""
    monkeypatch.setenv("AEGIS_HOST_IP", "")
    monkeypatch.setenv("HOST_IP", "")
    ip = netutils.detect_host_ip()
    assert ip
    assert ip != ""


def test_never_returns_loopback(monkeypatch):
    """Ключевая гарантия: 127.0.0.1 ломал проверку DNS у доменов и давал
    приложениям маркетплейса ссылки на localhost."""
    monkeypatch.delenv("AEGIS_HOST_IP", raising=False)
    monkeypatch.delenv("HOST_IP", raising=False)
    assert not netutils.detect_host_ip().startswith("127.")


def test_falls_back_when_detection_fails(monkeypatch):
    """Если определить адрес не удалось — отдаём осмысленный фолбэк, а не пусто."""
    monkeypatch.delenv("AEGIS_HOST_IP", raising=False)
    monkeypatch.delenv("HOST_IP", raising=False)

    class BrokenSocket:
        def __init__(self, *a, **k): raise OSError("no network")

    import socket as real_socket
    monkeypatch.setattr(real_socket, "socket", BrokenSocket)
    assert netutils.detect_host_ip() == "172.20.0.1"
