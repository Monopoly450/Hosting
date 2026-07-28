"""Ограничение частоты создающих операций.

Квоты ограничивают итоговый объём, но не темп: цикл «создать — удалить»
укладывается в квоту бесконечно и при этом нагружает Kubernetes и очередь.
"""
import os
import sys
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException

from app.core import ratelimit


@pytest.fixture(autouse=True)
def clean():
    ratelimit.reset_rate_limits()
    yield
    ratelimit.reset_rate_limits()


def student(uid=1):
    return types.SimpleNamespace(id=uid, role="student")


def admin(uid=99):
    return types.SimpleNamespace(id=uid, role="admin")


def test_requests_under_limit_pass():
    u = student()
    for _ in range(5):
        ratelimit.check_rate_limit(u, "create_vm", limit=5, window=60)


def test_exceeding_limit_raises_429():
    u = student()
    for _ in range(3):
        ratelimit.check_rate_limit(u, "create_vm", limit=3, window=60)
    with pytest.raises(HTTPException) as e:
        ratelimit.check_rate_limit(u, "create_vm", limit=3, window=60)
    assert e.value.status_code == 429


def test_429_tells_when_to_retry():
    u = student()
    ratelimit.check_rate_limit(u, "create_vm", limit=1, window=60)
    with pytest.raises(HTTPException) as e:
        ratelimit.check_rate_limit(u, "create_vm", limit=1, window=60)
    assert "Retry-After" in (e.value.headers or {})


def test_limits_are_per_user():
    """Один пользователь не должен исчерпывать лимит другому."""
    for _ in range(3):
        ratelimit.check_rate_limit(student(1), "create_vm", limit=3, window=60)
    ratelimit.check_rate_limit(student(2), "create_vm", limit=3, window=60)


def test_limits_are_per_action():
    """Создание ВМ не должно съедать лимит создания баз данных."""
    u = student()
    for _ in range(3):
        ratelimit.check_rate_limit(u, "create_vm", limit=3, window=60)
    ratelimit.check_rate_limit(u, "create_database", limit=3, window=60)


def test_admin_is_not_limited():
    a = admin()
    for _ in range(50):
        ratelimit.check_rate_limit(a, "create_vm", limit=1, window=60)


def test_window_slides(monkeypatch):
    """После окна счётчик освобождается."""
    u = student()
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])

    for _ in range(3):
        ratelimit.check_rate_limit(u, "create_vm", limit=3, window=60)
    with pytest.raises(HTTPException):
        ratelimit.check_rate_limit(u, "create_vm", limit=3, window=60)

    now[0] += 61          # окно прошло
    ratelimit.check_rate_limit(u, "create_vm", limit=3, window=60)


def test_known_actions_have_sane_defaults():
    for action in ("create_vm", "create_cluster", "create_database",
                   "create_deployment", "marketplace_deploy"):
        limit, window = ratelimit.DEFAULT_LIMITS[action]
        assert 1 <= limit <= 60 and window >= 60


def test_state_does_not_grow_without_bound(monkeypatch):
    """Записи протухших пользователей не должны копиться в памяти."""
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    for uid in range(1100):
        ratelimit.check_rate_limit(student(uid), "create_vm", limit=5, window=60)
    now[0] += 600
    ratelimit.check_rate_limit(student(9999), "create_vm", limit=5, window=60)
    assert len(ratelimit._events) < 1100
