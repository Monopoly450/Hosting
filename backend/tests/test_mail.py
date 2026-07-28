"""Создание почтового ящика: аргументы команды и честность результата.

Команда раньше собиралась строкой, которую docker SDK разбирал через shlex:
пароль с пробелом молча становился двумя аргументами, а пароль с апострофом
ронял разбор. Само исключение при этом маскировалось под успех (`return True`),
и в БД появлялся ящик, которого на сервере нет.
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

from app.api import mail


class FakeContainer:
    def __init__(self, exit_code=0):
        self.exit_code = exit_code
        self.received = None

    def exec_run(self, cmd):
        self.received = cmd
        return self.exit_code, b"ok"


def _patch_docker(monkeypatch, container):
    fake = types.SimpleNamespace(
        containers=types.SimpleNamespace(get=lambda name: container)
    )
    monkeypatch.setattr(mail.docker, "from_env", lambda: fake)


# --------------------------- аргументы команды ------------------------------

def test_command_is_a_list_not_a_string(monkeypatch):
    """Список не проходит через shlex — значение уходит как есть."""
    c = FakeContainer()
    _patch_docker(monkeypatch, c)
    mail.manage_docker_mailserver("add", "u@example.com", "simple123")
    assert isinstance(c.received, list)
    assert c.received == ["setup", "email", "add", "u@example.com", "simple123"]


def test_password_with_space_stays_one_argument(monkeypatch):
    """Раньше строка "…add u@x пароль с пробелом" давала лишние аргументы."""
    c = FakeContainer()
    _patch_docker(monkeypatch, c)
    mail.manage_docker_mailserver("add", "u@example.com", "two words")
    assert c.received[-1] == "two words"
    assert len(c.received) == 5


def test_password_with_quote_does_not_break(monkeypatch):
    """Апостроф ронял shlex.split с ValueError."""
    c = FakeContainer()
    _patch_docker(monkeypatch, c)
    assert mail.manage_docker_mailserver("add", "u@example.com", "it's ok") is True
    assert c.received[-1] == "it's ok"


def test_delete_does_not_pass_password(monkeypatch):
    c = FakeContainer()
    _patch_docker(monkeypatch, c)
    mail.manage_docker_mailserver("del", "u@example.com")
    assert c.received == ["setup", "email", "del", "u@example.com"]


def test_unknown_action_rejected():
    assert mail.manage_docker_mailserver("wipe", "u@example.com") is False


# ---------------------------- честность результата --------------------------

def test_nonzero_exit_is_failure(monkeypatch):
    _patch_docker(monkeypatch, FakeContainer(exit_code=1))
    assert mail.manage_docker_mailserver("add", "u@example.com", "pw123456") is False


def test_unreachable_server_reports_failure(monkeypatch):
    """Ключевая гарантия: панель не должна записывать в БД несуществующий ящик."""
    monkeypatch.delenv("MAIL_ALLOW_OFFLINE", raising=False)

    def boom():
        raise RuntimeError("docker unavailable")
    monkeypatch.setattr(mail.docker, "from_env", boom)

    assert mail.manage_docker_mailserver("add", "u@example.com", "pw123456") is False


def test_offline_mode_is_opt_in(monkeypatch):
    """Прежнее поведение осталось доступно, но только явным включением."""
    monkeypatch.setenv("MAIL_ALLOW_OFFLINE", "1")

    def boom():
        raise RuntimeError("docker unavailable")
    monkeypatch.setattr(mail.docker, "from_env", boom)

    assert mail.manage_docker_mailserver("add", "u@example.com", "pw123456") is True


# ------------------------------- валидация ----------------------------------

def test_short_password_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        mail.MailboxCreateRequest(email="u@example.com", password="short")


def test_empty_password_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        mail.MailboxCreateRequest(email="u@example.com", password="")


def test_reasonable_password_accepted():
    req = mail.MailboxCreateRequest(email="u@example.com", password="goodpass123")
    assert req.password == "goodpass123"
