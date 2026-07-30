"""Удаление ВМ должно отвязывать всё, что на неё ссылается.

Баг, найденный на живом сервере: синхронизация в /api/host/metrics отвязывала
базы данных и сетевые диски, но не деплои — а у AppDeployment есть внешний ключ
vm_id. Из-за этого db.delete(vm) падал с ForeignKeyViolation, commit
откатывался, и синхронизация переставала работать ЦЕЛИКОМ: статусы всех
остальных ВМ больше не обновлялись, а в логи каждые несколько секунд летела
ошибка.

Тест сравнивает список внешних ключей в модели с тем, что реально обрабатывается
в коде, — чтобы новый FK нельзя было добавить, забыв про удаление.
"""
import os
import re
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


def _source(rel_path: str) -> str:
    with open(os.path.join(APP_DIR, rel_path), encoding="utf-8") as f:
        return f.read()


def test_model_declares_the_foreign_keys_we_expect():
    """Если появится новый FK на vm_tasks, тест ниже потребует его обработки."""
    from app.models.models import UserDatabase, UserVolume, AppDeployment

    assert UserDatabase.associated_vm_id is not None
    assert UserVolume.attached_vm_id is not None
    assert AppDeployment.vm_id is not None


def test_every_fk_column_to_vm_tasks_is_known():
    """Ловим появление нового внешнего ключа на vm_tasks."""
    src = _source("models/models.py")
    columns = re.findall(r'(\w+)\s*=\s*Column\([^)]*ForeignKey\("vm_tasks\.id"\)', src)
    assert set(columns) == {"associated_vm_id", "attached_vm_id", "vm_id"}, (
        f"появился новый внешний ключ на vm_tasks: {columns}. "
        "Добавьте его отвязку во все места, где удаляется VMTask."
    )


@pytest.mark.parametrize("path,label", [
    ("api/host.py", "синхронизация метрик хоста"),
    ("api/clusters.py", "удаление кластера"),
])
def test_deletion_sites_detach_all_references(path, label):
    """Каждое место, где удаляется VMTask, обязано отвязать все три ссылки."""
    src = _source(path)
    assert "db.delete(vm)" in src, f"{label}: ожидалось удаление ВМ"

    for column, table in (
        ("associated_vm_id", "UserDatabase"),
        ("attached_vm_id", "UserVolume"),
        ("vm_id", "AppDeployment"),
    ):
        assert table in src and column in src, (
            f"{label}: не отвязывается {table}.{column} — "
            f"db.delete(vm) упадёт с ForeignKeyViolation"
        )


def test_deployment_deletion_removes_deployment_before_vm():
    """В deployments.py порядок обратный: сначала деплой, потом его ВМ.
    Тогда отвязка не нужна, но порядок нарушать нельзя."""
    src = _source("api/deployments.py")
    pos_dep = src.find("db.delete(dep)")
    pos_vm = src.find("db.delete(vmt)")
    assert pos_dep != -1 and pos_vm != -1
    assert pos_dep < pos_vm, "деплой должен удаляться раньше своей ВМ"


def test_broken_deployment_is_marked_not_silently_kept():
    """Деплой без ВМ нерабочий — он должен быть помечен, а не тихо остаться
    выглядящим живым."""
    for path in ("api/host.py", "api/clusters.py"):
        src = _source(path)
        block = src[src.find("AppDeployment.vm_id == vm.id"):]
        assert '"status": "Error"' in block[:300], (
            f"{path}: у осиротевшего деплоя не выставляется статус Error"
        )
