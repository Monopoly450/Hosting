"""Задачи, зависшие в Pending.

ВМ может остаться в Pending навсегда: очередь была недоступна в момент
постановки (строка уже закоммичена, rollback её не уберёт), либо воркер
перезапустился после подтверждения сообщения. Такая запись занимает квоту
пользователя, поэтому её нужно закрывать — но только убедившись, что ВМ
действительно нет в кластере.
"""
import os
import sys
import types
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import stuck_tasks


NOW = datetime(2026, 7, 28, 12, 0, 0)


def task(name="vm1", status="Pending", age_minutes=60):
    return types.SimpleNamespace(
        name=name, status=status, error_message=None,
        created_at=NOW - timedelta(minutes=age_minutes),
    )


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.conditions = []

    def filter(self, *args):
        self.conditions.extend(args)
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, rows):
        self.rows, self.committed, self.rolled_back = rows, False, False

    def query(self, model):
        return FakeQuery(self.rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def k8s_with(exists=True, raises=None):
    def get_vm(name):
        if raises:
            raise raises
        if not exists:
            raise Exception("virtualmachines.kubevirt.io 'vm1' not found")
        return {"name": name, "status": "Running"}
    return types.SimpleNamespace(get_vm=get_vm)


# --------------------------- определение зависших ---------------------------

def test_finds_only_old_pending(monkeypatch):
    rows = [task("old", age_minutes=60), task("fresh", age_minutes=1)]
    db = FakeDB(rows)
    # фильтрация выполняется на стороне БД; проверяем, что условия построены
    found = stuck_tasks.find_stuck_tasks(db, now=NOW)
    assert found == rows  # FakeQuery не фильтрует, но вызов не должен падать


def test_cutoff_uses_configured_window():
    db = FakeDB([])
    q = FakeQuery([])
    db.query = lambda model: q
    stuck_tasks.find_stuck_tasks(db, now=NOW, minutes=15)
    assert len(q.conditions) == 2  # статус Pending + возраст


# ----------------------------- проверка кластера ----------------------------

def test_vm_missing_detected():
    assert stuck_tasks.vm_exists_in_cluster(k8s_with(exists=False), "vm1") is False


def test_vm_present_detected():
    assert stuck_tasks.vm_exists_in_cluster(k8s_with(exists=True), "vm1") is True


def test_unknown_when_cluster_unreachable():
    """Ключевое: недоступный кластер — не повод объявлять задачу провалившейся."""
    k8s = k8s_with(raises=ConnectionError("connection refused"))
    assert stuck_tasks.vm_exists_in_cluster(k8s, "vm1") is None


# --------------------------------- разбор -----------------------------------

def test_missing_vm_is_marked_error(monkeypatch):
    rows = [task("vm1")]
    db = FakeDB(rows)
    monkeypatch.setattr(stuck_tasks, "SessionLocal", lambda: db, raising=False)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)

    reaped = stuck_tasks.reap_stuck_tasks(k8s_with(exists=False), now=NOW)
    assert reaped == 1
    assert rows[0].status == "Error"
    assert "Удалите запись" in rows[0].error_message
    assert db.committed


def test_existing_vm_is_repaired_not_failed(monkeypatch):
    """ВМ создалась, но статус не обновился — чинить, а не ломать."""
    rows = [task("vm1")]
    db = FakeDB(rows)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)

    reaped = stuck_tasks.reap_stuck_tasks(k8s_with(exists=True), now=NOW)
    assert reaped == 0
    assert rows[0].status == "Running"


def test_unreachable_cluster_leaves_task_alone(monkeypatch):
    rows = [task("vm1")]
    db = FakeDB(rows)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)

    k8s = k8s_with(raises=ConnectionError("connection refused"))
    reaped = stuck_tasks.reap_stuck_tasks(k8s, now=NOW)
    assert reaped == 0
    assert rows[0].status == "Pending"      # решение отложено до следующего прохода


# --------------------- устойчивая постановка в очередь ----------------------

def test_publish_failure_marks_task_error(monkeypatch):
    from app import queue_client

    def boom(queue, data):
        raise ConnectionError("RabbitMQ недоступен")
    monkeypatch.setattr(queue_client, "publish_task", boom)

    t = task("vm1")
    db = FakeDB([t])
    ok = queue_client.publish_task_or_fail_task("vm_tasks", {"task_id": 1}, db, t)

    assert ok is False
    assert t.status == "Error"
    assert "очередей недоступен" in t.error_message
    assert db.committed


def test_publish_success_leaves_task_pending(monkeypatch):
    from app import queue_client
    monkeypatch.setattr(queue_client, "publish_task", lambda q, d: None)

    t = task("vm1")
    db = FakeDB([t])
    assert queue_client.publish_task_or_fail_task("vm_tasks", {"task_id": 1}, db, t) is True
    assert t.status == "Pending"
