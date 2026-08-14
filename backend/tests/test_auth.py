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


def test_login_form_is_recognisable_to_password_managers():
    """Менеджер паролей браузера опознаёт форму входа по name и autocomplete.
    Без них он не предлагает сохранить пароль и не подставляет его при
    следующем входе — «запомнить меня» выглядит неработающим, хотя оно про
    срок жизни сессии, а не про подстановку."""
    import os, re
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend", "src", "App.jsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    card = src[src.index('className="login-card"'):]
    card = card[:card.index("Защищённое соединение")]
    assert 'autoComplete="username"' in card
    assert 'autoComplete="current-password"' in card
    assert 'name="username"' in card and 'name="password"' in card


def test_remember_me_only_changes_the_session_lifetime():
    """Галочка продлевает токен, а не хранит пароль: хранить его панели
    негде и незачем — это работа менеджера паролей."""
    from app.api.auth import DEFAULT_SESSION_SECONDS, REMEMBER_ME_SECONDS

    assert DEFAULT_SESSION_SECONDS == 3600 * 24
    assert REMEMBER_ME_SECONDS > DEFAULT_SESSION_SECONDS
    # Не бесконечно: токен лежит в localStorage, отозвать его поштучно нечем.
    assert REMEMBER_ME_SECONDS <= 3600 * 24 * 31


def test_panels_keep_their_header_while_loading():
    """Раньше пять панелей во время загрузки делали ранний return с одним
    спиннером — шапки не было вовсе, а когда данные приходили, она
    появлялась и весь контент прыгал вниз. Пользователь видел это как
    «панель разного размера на разных вкладках»."""
    import os, re, glob

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    bad = []
    for path in glob.glob(os.path.join(root, "frontend", "src", "components", "*.jsx")):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for m in re.finditer(r"if \(loading\) return.*?;", src, re.S):
            block = m.group(0)
            # Ранний выход допустим — но шапку он обязан отрисовать.
            if "{header}" not in block:
                bad.append(f"{os.path.basename(path)}: {block[:80]}")
    assert not bad, "ранний return без шапки:\n" + "\n".join(bad)


def test_loading_area_has_one_shared_height():
    """У каждой панели был свой отступ вокруг спиннера (50px, 60px,
    page-loading) — высота области загрузки отличалась от вкладки к вкладке."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "index.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".panel-loading" in css


def test_every_tab_uses_the_shared_header_layout():
    """Дашборд не имел строки описания вовсе, а «Серверы и Инстансы» держали
    свой inline-ряд с отступом от gap родителя вместо margin-bottom общего
    класса. Из-за этого контент на разных вкладках начинался на разной
    высоте — при том что верхняя панель везде одна и та же."""
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "App.jsx"), encoding="utf-8") as f:
        src = f.read()

    for marker in ("/* Dashboard View */", "/* Combined Servers List */"):
        start = src.index(marker)
        block = src[start:start + 1200]
        assert 'className="panel-header"' in block, f"{marker}: своя вёрстка вместо общей"

    # Своя разметка «заголовок вкладки» с inline-стилями не должна вернуться:
    # именно она разъезжалась по отступам с остальными панелями.
    assert "fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-heading)'" not in src
