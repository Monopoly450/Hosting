"""Асинхронная сессия не должна инвалидировать объекты после commit.

Найдено на живом сервере. По умолчанию SQLAlchemy после commit() помечает
объекты устаревшими, и первое же чтение атрибута тянет SELECT для обновления.
В асинхронном режиме этот неявный запрос выполняется вне greenlet-контекста:

    MissingGreenlet: greenlet_spawn has not been called;
    can't call await_only() here

Падало всё, где после commit читается поле объекта: настройка 2FA (нужен
current_user.username для otpauth-ссылки) и вход по резервному коду — расход
кода делает commit, после которого читается user.username для выдачи токена.
То есть, включив 2FA, войти резервным кодом было нельзя.
"""
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


def _source(rel):
    with open(os.path.join(APP_DIR, rel), encoding="utf-8") as f:
        return f.read()


def test_async_session_keeps_objects_usable_after_commit():
    """Ключевая настройка: без неё любое чтение поля после commit даёт 500."""
    from app.core.database import SessionLocal

    assert SessionLocal.kw.get("expire_on_commit") is False, (
        "expire_on_commit должен быть False: иначе чтение атрибута после commit "
        "вызывает неявный SELECT вне greenlet и падает с MissingGreenlet"
    )


def test_async_session_does_not_autocommit():
    """Заодно закрепляем остальные ожидания от фабрики сессий."""
    from app.core.database import SessionLocal

    assert SessionLocal.kw.get("autocommit") is False
    assert SessionLocal.kw.get("autoflush") is False


def test_login_snapshots_user_fields_before_second_factor():
    """Проверка второго фактора расходует резервный код и делает commit,
    поэтому поля для ответа снимаются заранее."""
    src = _source("api/auth.py")
    login = src[src.find("async def login("):src.find("@router.post(\"/register\"")]

    pos_snapshot = login.find("username, user_role = user.username, user.role")
    pos_verify = login.find("verify_second_factor")
    assert pos_snapshot != -1, "поля пользователя должны сниматься до проверки кода"
    assert pos_snapshot < pos_verify

    # в ответе используются снятые значения, а не повторное чтение объекта
    tail = login[login.find("token = create_access_token"):]
    assert "user.username" not in tail
    assert "user.role" not in tail


def test_totp_setup_reads_username_before_commit():
    src = _source("api/auth.py")
    setup = src[src.find("async def totp_setup("):src.find("async def totp_enable(")]

    pos_read = setup.find("username = current_user.username")
    pos_commit = setup.find("await db.commit()")
    assert pos_read != -1 and pos_commit != -1
    assert pos_read < pos_commit, "имя нужно прочитать до commit"


def test_qr_failure_does_not_break_enrolment():
    """QR — удобство; подключиться можно вводом ключа вручную."""
    src = _source("api/auth.py")
    setup = src[src.find("async def totp_setup("):src.find("async def totp_enable(")]
    assert "qr_svg = None" in setup
    assert "except Exception" in setup


def test_auth_module_has_a_logger():
    """Логирование в except-ветке не должно само бросать NameError."""
    src = _source("api/auth.py")
    assert "import logging" in src
    assert 'logger = logging.getLogger("app.api.auth")' in src
