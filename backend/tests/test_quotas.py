"""Квоты: подсчёт занятого и защита от гонки.

Проверка «сколько занято» и вставка ресурса — разные операции. Без блокировки
строки пользователя два одновременных запроса читают одно состояние, оба
проходят проверку и оба создают ресурс: лимит в 2 ВМ превращается в 3.
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

from app.core import quotas


def user(role="student", max_vms=2, max_vcpus=4, max_ram_mb=4096, max_storage_gb=40):
    return types.SimpleNamespace(id=1, role=role, max_vms=max_vms, max_vcpus=max_vcpus,
                                 max_ram_mb=max_ram_mb, max_storage_gb=max_storage_gb)


def vm(cpu=1, ram=1, disk=10):
    return types.SimpleNamespace(cpu_cores=cpu, memory_gb=ram, disk_gb=disk)


class FakeQuery:
    def __init__(self, db, model):
        self.db, self.model = db, model

    def filter(self, *a, **k):
        return self

    def with_for_update(self):
        self.db.locked = True          # фиксируем факт блокировки
        return self

    def first(self):
        return self.db.user

    def all(self):
        return self.db.vms


class FakeDB:
    def __init__(self, owned_vms, current_user):
        self.vms, self.user, self.locked = owned_vms, current_user, False

    def query(self, model):
        return FakeQuery(self, model)

    def rollback(self):
        pass


# ------------------------------ подсчёт -------------------------------------

def test_usage_sums_resources():
    db = FakeDB([vm(2, 4, 20), vm(1, 2, 10)], user())
    used = quotas.current_usage(db, 1)
    assert used == {"vms": 2, "vcpus": 3, "ram_mb": 6 * 1024, "storage_gb": 30}


def test_usage_tolerates_null_fields():
    """У задачи в статусе Pending поля могут быть не заполнены."""
    db = FakeDB([types.SimpleNamespace(cpu_cores=None, memory_gb=None, disk_gb=None)], user())
    assert quotas.current_usage(db, 1)["vcpus"] == 0


# ------------------------------ проверки ------------------------------------

def test_within_quota_passes():
    db = FakeDB([vm(1, 1, 10)], user())
    quotas.enforce_quota(db, db.user, add_vms=1, add_vcpus=1, add_ram_gb=1, add_storage_gb=10)


def test_vm_count_limit():
    db = FakeDB([vm(), vm()], user(max_vms=2))
    with pytest.raises(HTTPException) as e:
        quotas.enforce_quota(db, db.user, add_vms=1)
    assert "количество виртуальных машин" in e.value.detail


def test_cpu_limit():
    db = FakeDB([vm(cpu=3)], user(max_vcpus=4))
    with pytest.raises(HTTPException) as e:
        quotas.enforce_quota(db, db.user, add_vms=1, add_vcpus=2)
    assert "ядра процессора" in e.value.detail


def test_ram_limit():
    db = FakeDB([vm(ram=3)], user(max_ram_mb=4096))
    with pytest.raises(HTTPException) as e:
        quotas.enforce_quota(db, db.user, add_vms=1, add_ram_gb=2)
    assert "оперативной памяти" in e.value.detail


def test_storage_limit():
    db = FakeDB([vm(disk=35)], user(max_storage_gb=40))
    with pytest.raises(HTTPException) as e:
        quotas.enforce_quota(db, db.user, add_vms=1, add_storage_gb=10)
    assert "дисковое пространство" in e.value.detail


def test_admin_is_not_limited():
    db = FakeDB([vm() for _ in range(50)], user(role="admin", max_vms=1))
    quotas.enforce_quota(db, db.user, add_vms=10, add_vcpus=99)


def test_cluster_sized_request_counted_as_a_whole():
    """Кластер из 3 ВМ не должен пролезать по одной."""
    db = FakeDB([], user(max_vms=2))
    with pytest.raises(HTTPException):
        quotas.enforce_quota(db, db.user, add_vms=3)


# ------------------------------- гонка --------------------------------------

def test_user_row_is_locked_before_counting():
    """Ключевая гарантия: без SELECT FOR UPDATE параллельные запросы
    проскакивают проверку вдвоём."""
    db = FakeDB([vm()], user())
    quotas.enforce_quota(db, db.user, add_vms=1)
    assert db.locked, "строка пользователя должна блокироваться до подсчёта"


def test_limits_are_read_from_locked_row():
    """Лимиты берём из заблокированной записи, а не из объекта запроса:
    админ мог изменить квоту, пока запрос был в пути."""
    stale = user(max_vms=99)                 # то, что пришло с токеном
    fresh = user(max_vms=1)                  # то, что сейчас в БД
    db = FakeDB([vm()], fresh)
    with pytest.raises(HTTPException):
        quotas.enforce_quota(db, stale, add_vms=1)


def test_lock_failure_does_not_break_check(monkeypatch):
    """Если БД не умеет FOR UPDATE, проверка всё равно должна отработать."""
    class NoLockDB(FakeDB):
        def query(self, model):
            q = FakeQuery(self, model)
            def boom():
                raise RuntimeError("FOR UPDATE не поддерживается")
            q.with_for_update = boom
            return q

    db = NoLockDB([vm(), vm()], user(max_vms=2))
    with pytest.raises(HTTPException):
        quotas.enforce_quota(db, db.user, add_vms=1)
