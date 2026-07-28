"""Серверные ошибки не должны раскрывать внутренние детали наружу.

Раньше обработчики отдавали клиенту str(e) — трейсбеки kubernetes, пути на
диске, SQL и адреса внутренних сервисов. Теперь 5xx маскируются, а полный
текст уходит в лог с кодом обращения. Сообщения 4xx остаются как есть.
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

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import masked_http_exception_handler, unhandled_exception_handler

SECRET = "postgresql://postgres:hunter2@10.0.0.5:5432/aegis"


@pytest.fixture()
def client():
    """Мини-приложение с теми же обработчиками, что и у панели."""
    app = FastAPI()
    app.add_exception_handler(HTTPException, masked_http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boom500")
    def boom500():
        raise HTTPException(status_code=500, detail=f"Ошибка подключения: {SECRET}")

    @app.get("/boom502")
    def boom502():
        raise HTTPException(status_code=502, detail=f"upstream: {SECRET}")

    @app.get("/quota")
    def quota():
        raise HTTPException(status_code=400, detail="Превышена квота на ядра CPU (лимит: 4).")

    @app.get("/totp")
    def totp():
        raise HTTPException(status_code=401, detail="TOTP_REQUIRED")

    @app.get("/unhandled")
    def unhandled():
        raise RuntimeError(f"внезапно упало: {SECRET}")

    return TestClient(app, raise_server_exceptions=False)


def test_500_hides_internal_detail(client):
    r = client.get("/boom500")
    assert r.status_code == 500
    body = r.text
    assert SECRET not in body
    assert "hunter2" not in body
    assert "Внутренняя ошибка сервера" in r.json()["detail"]


def test_500_returns_traceable_error_id(client):
    """Админ должен суметь найти полный текст в логах по коду из ответа."""
    detail = client.get("/boom500").json()["detail"]
    assert re.search(r"Код обращения: [0-9a-f]{12}", detail)


def test_error_ids_are_unique(client):
    a = client.get("/boom500").json()["detail"]
    b = client.get("/boom500").json()["detail"]
    assert a != b


def test_all_5xx_are_masked(client):
    r = client.get("/boom502")
    assert r.status_code == 502
    assert SECRET not in r.text


def test_4xx_messages_are_preserved(client):
    """Осмысленные сообщения клиенту трогать нельзя."""
    r = client.get("/quota")
    assert r.status_code == 400
    assert r.json()["detail"] == "Превышена квота на ядра CPU (лимит: 4)."


def test_totp_required_marker_survives(client):
    """На этот маркер завязан фронтенд — форма входа показывает поле кода."""
    r = client.get("/totp")
    assert r.status_code == 401
    assert r.json()["detail"] == "TOTP_REQUIRED"


def test_unhandled_exception_is_masked(client):
    r = client.get("/unhandled")
    assert r.status_code == 500
    assert SECRET not in r.text
    assert "RuntimeError" not in r.text
    assert re.search(r"Код обращения: [0-9a-f]{12}", r.json()["detail"])


def test_full_detail_goes_to_log(client, caplog):
    with caplog.at_level("ERROR", logger="app.main"):
        client.get("/boom500")
    assert SECRET in caplog.text  # админ видит полный текст в логах
