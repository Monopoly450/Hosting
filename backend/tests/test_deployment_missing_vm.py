"""Деплой, у которого нет ВМ: сообщения вместо сырых ответов Kubernetes.

Если ВМ не создалась (сбой воркера или очереди), вкладка логов показывала
ответ Kubernetes целиком — с заголовками, Audit-Id и JSON-телом. Пользователю
из этого не ясно ни что случилось, ни что делать. Отсутствие ВМ и
недоступность кластера — разные ситуации, и различать их нужно явно.
"""
import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.deployments import _is_vm_missing


class ApiExc(Exception):
    def __init__(self, status, message=""):
        super().__init__(message)
        self.status = status


REAL_404 = (
    '(404)\nReason: Not Found\nHTTP response headers: HTTPHeaderDict({\'Audit-Id\': '
    "'ef41b226-107e-43a1-a499-d89cd8cac4ff'})\nHTTP response body: "
    '{"kind":"Status","status":"Failure","message":"virtualmachines.kubevirt.io '
    '\\"nextcloud-xpq3\\" not found","reason":"NotFound","code":404}'
)


def test_detects_missing_vm_by_status_attribute():
    assert _is_vm_missing(ApiExc(404)) is True


def test_detects_missing_vm_in_real_kubernetes_message():
    """Именно такой текст видел пользователь на вкладке логов."""
    assert _is_vm_missing(Exception(REAL_404)) is True


@pytest.mark.parametrize("exc", [
    ApiExc(500, "internal error"),
    ApiExc(403, "forbidden"),
    ConnectionError("connection refused"),
    Exception("timeout while connecting to cluster"),
])
def test_other_failures_are_not_treated_as_missing(exc):
    """Недоступность кластера нельзя выдавать за отсутствие ВМ — иначе
    пользователю предложат удалить рабочий деплой."""
    assert _is_vm_missing(exc) is False


def test_missing_vm_message_is_actionable():
    """В ответе должно быть сказано, что делать, и не должно быть внутренностей."""
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "deployments.py",
    )
    with open(src_path, encoding="utf-8") as f:
        src = f.read()

    block = src[src.find("if _is_vm_missing(e):"):]
    assert "Удалите этот деплой" in block[:800]
    assert "Audit-Id" not in block[:800]
