"""Балансировщик не должен занимать порты самой платформы.

nginx поднимает пул в сети хоста. Если порт уже занят (панелью, Caddy, API),
nginx не перезагрузится — и вместе с новым пулом перестанут работать все
остальные. Самый неприятный случай: пул на 8080 отрезает доступ к панели.
"""
import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.vms import RESERVED_HOST_PORTS


@pytest.mark.parametrize("port,why", [
    (8080, "веб-панель — пул на этом порту отрезал бы доступ к интерфейсу"),
    (8443, "веб-панель по HTTPS"),
    (80, "aegis-caddy: без него не пройдёт HTTP-01 проверка Let's Encrypt"),
    (443, "aegis-caddy: HTTPS своих доменов"),
    (8000, "API бэкенда"),
    (8001, "Go-оркестратор"),
    (5000, "приватный реестр образов"),
    (5432, "PostgreSQL"),
    (5672, "RabbitMQ"),
    (15672, "консоль RabbitMQ"),
    (3306, "MariaDB"),
    (9000, "MinIO S3 API"),
    (9001, "консоль MinIO"),
    (25, "SMTP"),
    (993, "IMAPS"),
])
def test_platform_ports_are_reserved(port, why):
    assert port in RESERVED_HOST_PORTS, f"порт {port} должен быть занят: {why}"


@pytest.mark.parametrize("port", [8090, 10000, 12345, 20000, 31000])
def test_free_ports_are_allowed(port):
    """Обычные пользовательские порты остаются доступными."""
    assert port not in RESERVED_HOST_PORTS


def test_reserved_set_covers_compose_bindings():
    """Список синхронизирован с реальными биндингами docker-compose."""
    import re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    compose = open(os.path.join(root, "docker-compose.yml"), encoding="utf-8").read()

    published = set()
    for m in re.finditer(r'^\s+- "(?:127\.0\.0\.1:)?(\d+):\d+"', compose, re.M):
        published.add(int(m.group(1)))

    missing = published - RESERVED_HOST_PORTS
    assert not missing, f"порты из docker-compose не защищены: {sorted(missing)}"
