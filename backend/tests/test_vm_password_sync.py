"""Пароль в Secret должен совпадать с паролем внутри ВМ.

Баг, найденный на живом сервере. Воркер генерировал пароль и писал его в
Secret, но generate_linux_manifest игнорирует переданный пароль, если
custom_user_data задан извне — а у деплоев и маркетплейса он задан всегда,
со своим паролем. В результате Secret содержал пароль, которого в системе
никогда не было, и панель не могла зайти в ВМ по SSH: не работали логи
сборки, веб-терминал и подсказка подключения.
"""
import os
import re
import sys
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


def _source(rel):
    with open(os.path.join(APP_DIR, rel), encoding="utf-8") as f:
        return f.read()


def task(custom_user_data=None, vm_password=None, name="vm1"):
    return types.SimpleNamespace(
        name=name, custom_user_data=custom_user_data, vm_password=vm_password
    )


# ------------------------- выбор пароля в воркере ---------------------------

def test_stored_password_used_when_cloud_init_is_external():
    """Главная гарантия: при внешнем cloud-init берём сохранённый пароль."""
    from app.core.crypto import encrypt_secret
    from app.services.vm_credentials import resolve_vm_password

    secret = "PasswordFromDeploy123"
    t = task(custom_user_data="#cloud-config\n...", vm_password=encrypt_secret(secret))
    assert resolve_vm_password(t) == secret


def test_random_password_when_no_custom_cloud_init():
    """Обычная ВМ: cloud-init генерируется здесь же, пароль случайный."""
    from app.services.vm_credentials import resolve_vm_password

    a = resolve_vm_password(task())
    b = resolve_vm_password(task())
    assert a and b and a != b


def test_random_password_when_custom_cloud_init_without_stored():
    """Пользователь принёс свой cloud-init, но пароля мы не знаем —
    генерируем, ломаться не должно."""
    from app.services.vm_credentials import resolve_vm_password

    pw = resolve_vm_password(task(custom_user_data="#cloud-config\n..."))
    assert pw


def test_broken_encryption_falls_back_instead_of_crashing():
    """Нерасшифровываемое значение не должно ронять создание ВМ."""
    from app.services.vm_credentials import resolve_vm_password

    t = task(custom_user_data="#cloud-config", vm_password="не-шифртекст")
    assert resolve_vm_password(t)


# --------------------- пароль сохраняется при создании ----------------------

def test_deployment_stores_the_password_it_wrote():
    """deployments.py должен сохранять тот же пароль, что попал в cloud-init."""
    src = _source("api/deployments.py")
    assert "vm_password=encrypt_secret(password)" in src


def test_marketplace_stores_the_password_it_wrote():
    src = _source("api/marketplace.py")
    assert "vm_password = encrypt_secret(password)" in src


def test_clone_carries_password_over():
    """Клон грузится с cloud-init источника, значит пароль тот же."""
    src = _source("api/vms.py")
    assert "vm_password=source.vm_password" in src


def test_password_is_stored_encrypted():
    """В БД пароль не должен лежать открытым текстом."""
    for rel in ("api/deployments.py", "api/marketplace.py"):
        src = _source(rel)
        assert "encrypt_secret" in src, f"{rel}: пароль сохраняется без шифрования"


def test_model_and_migration_agree():
    """Поле есть и в модели, и в миграциях — иначе обновление сломается."""
    assert "vm_password" in _source("models/models.py")
    assert "vm_password" in _source("core/migrations.py")


def test_worker_no_longer_generates_password_blindly():
    """В обоих путях воркера (создание и клонирование) используется
    resolve_vm_password, а не прямая генерация."""
    src = _source("worker.py")
    body = src[src.find("def process_vm_task"):]
    assert body.count("resolve_vm_password(task)") >= 2
