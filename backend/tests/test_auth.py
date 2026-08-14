import time

from app.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


def test_password_hash_and_verify():
    hashed = hash_password("my-password")
    assert hashed != "my-password"
    assert verify_password("my-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


def test_verify_malformed_hash():
    assert not verify_password("any", "not-a-valid-hash")
    assert not verify_password("any", "")


def test_token_roundtrip():
    token = create_access_token({"sub": "student1"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "student1"


def test_expired_token_rejected():
    token = create_access_token({"sub": "student1"}, expires_delta=-10)
    assert decode_access_token(token) is None


def test_tampered_token_rejected():
    token = create_access_token({"sub": "student1"})
    payload_str, sig = token.split(".")
    # Подмена подписи
    assert decode_access_token(f"{payload_str}.AAAA{sig[4:]}") is None
    # Мусор вместо токена
    assert decode_access_token("garbage") is None
    assert decode_access_token("a.b.c") is None


# ----- «не представился» и «не админ» — это РАЗНЫЕ коды ответа --------------
#
# Живой баг: студент открывал вкладку «Кластеры», та запрашивала
# /api/host/metrics (роутер закрыт verify_admin_token), получала 401 — а
# перехватчик fetch в панели считает 401 протухшей сессией: стирал токен и
# перезагружал страницу. Вместо кластеров человек видел форму входа.

def test_admin_guard_separates_401_from_403():
    """401 — токена нет или он не наш; 403 — токен валиден, но роль не та."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "core", "auth.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    guard = src[src.index("async def verify_admin_token"):]
    guard = guard[:guard.index("API_TOKEN_PREFIX")]
    assert "HTTP_403_FORBIDDEN" in guard, "аутентифицированный неадмин обязан получать 403"
    assert "HTTP_401_UNAUTHORIZED" in guard, "анонимный запрос обязан получать 401"
    # 403 — только для того, кто успешно опознан.
    assert "if authenticated:" in guard


def test_frontend_logs_out_only_on_401():
    """Обратная сторона: перехватчик обязан реагировать именно на 401.
    Начни он выкидывать и на 403 — фикс выше стал бы бессмысленным."""
    import os, re
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend", "src", "main.jsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "response.status === 401" in src
    assert "403" not in src
