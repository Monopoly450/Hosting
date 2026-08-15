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


def test_top_header_cannot_be_squeezed_by_page_content():
    """Верхняя панель — flex-элемент внутри .main-area (flex-колонка в
    .app-layout с height: 100vh). У flex-элементов flex-shrink равен 1 по
    умолчанию, поэтому её сжимал сам контент страницы: пока данных мало —
    70px, как только они загрузились и перестали влезать в экран — меньше
    (замерено: 37px при 4000px контента). Отсюда «панель не зафиксирована»
    и разная её высота на разных вкладках. У .sidebar эта защита уже была."""
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "index.css"), encoding="utf-8") as f:
        css = f.read()

    # Комментарии вырезаем: в пояснении рядом упоминается height: 100vh
    # родителя, и наивная проверка по подстроке ловила именно его.
    code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    block = code[code.index(".top-header {"):]
    block = block[:block.index("}")]
    assert "flex-shrink: 0" in block, "верхнюю панель снова будет сжимать контент"
    assert "min-height: 70px" in block, "фиксированный height сжимается, min-height — нет"

    # Мобильное правило не должно вернуть height обратно: оно перебило бы
    # защиту из базового блока.
    for m in re.finditer(r"\.top-header \{[^}]*\}", code):
        assert not re.search(r"(?<!-)\bheight:\s*\d", m.group(0)), \
            f"height вместо min-height вернёт сжатие: {m.group(0)}"


def test_icon_sizes_stay_on_one_scale():
    """Размеров иконок было девятнадцать — от 10 до 48, причём для ОДНОЙ роли
    использовались разные: пустые состояния вкладок рисовались размерами 32,
    36, 38, 40, 44 и 48. Отсюда «в одних вкладках иконки маленькие, в других
    большие». Шкала описана в frontend/src/iconSizes.js."""
    import os, re, glob

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src_dir = os.path.join(root, "frontend", "src")

    allowed = {12, 14, 16, 18, 20, 24, 32, 44}
    # Логотипы — фирменный знак, а не иконка интерфейса.
    logo_marks = {26, 38}

    offenders = {}
    files = glob.glob(os.path.join(src_dir, "components", "*.jsx")) + [os.path.join(src_dir, "App.jsx")]
    for path in files:
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for m in re.finditer(r"size=\{(\d+)\}", line):
                    n = int(m.group(1))
                    if n in allowed:
                        continue
                    if n in logo_marks and ("logo" in line or "Layers" in line):
                        continue
                    offenders[f"{os.path.basename(path)}:{lineno}"] = n

    assert not offenders, (
        "иконки вне шкалы (см. frontend/src/iconSizes.js): "
        + ", ".join(f"{k}={v}" for k, v in sorted(offenders.items()))
    )


def test_icon_scale_is_documented():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "frontend", "src", "iconSizes.js")
    assert os.path.exists(path), "шкала размеров иконок должна быть описана в одном месте"


def test_no_styling_classes_that_do_not_exist():
    """Мониторинг внешнего сервера рисовал шкалы CPU/RAM/диска классами
    .progress-bar-bg и .progress-bar-fill, а подписи — .stat-item,
    .stat-label-container и .stat-value. Ни одного из них в index.css нет,
    поэтому шкалы не отрисовывались вообще: оставался голый текст, и экран
    выглядел незакончённым. Ошибка молчаливая — несуществующий класс просто
    ничего не делает."""
    import os, re, glob

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src_dir = os.path.join(root, "frontend", "src")
    with open(os.path.join(src_dir, "index.css"), encoding="utf-8") as f:
        css = f.read()

    # Классы, которыми пользуются экраны и которых не должно не быть.
    watched = [
        "progress-track", "progress-fill", "stat-box", "stat-box-title",
        "stat-box-value", "glass-card", "badge", "form-control", "panel-loading",
    ]
    for cls in watched:
        assert re.search(r"\.%s(?![\w-])" % re.escape(cls), css), f"нет .{cls} в index.css"

    # А эти — заведомо мёртвые: их не должно остаться в разметке.
    banned = ["progress-bar-bg", "progress-bar-fill", "stat-item",
              "stat-label-container", "stat-value", "form-input"]
    offenders = []
    for path in glob.glob(os.path.join(src_dir, "components", "*.jsx")) + [os.path.join(src_dir, "App.jsx")]:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        code = re.sub(r"/\*.*?\*/|\{/\*.*?\*/\}", "", src, flags=re.S)
        for cls in banned:
            if re.search(r'className="[^"]*\b%s\b' % re.escape(cls), code):
                offenders.append(f"{os.path.basename(path)}: {cls}")
    assert not offenders, "класс, которого нет в CSS: " + ", ".join(offenders)


def test_modals_render_outside_the_app_shell():
    """Модалка, отрисованная внутри .main-area, накрыть сайдбар не может:
    .main-area создаёт свой контекст наложения (position: relative +
    z-index), и z-index: 1000 у оверлея внутри неё выше соседей не
    поднимается. На экране это выглядело так — контент затемнён и размыт, а
    сайдбар остался светлым поверх оверлея, и окно центрировалось не по
    экрану. Лечится не z-index'ом, а порталом в document.body."""
    import os, re, glob

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src_dir = os.path.join(root, "frontend", "src")

    offenders = []
    for path in glob.glob(os.path.join(src_dir, "components", "*.jsx")):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if 'className="modal-overlay"' not in src:
            continue
        if "import Portal" not in src:
            offenders.append(os.path.basename(path))
    assert not offenders, "модалка вне <Portal>: " + ", ".join(offenders)

    # Костыль в CSS больше не должен упоминать .modal-overlay — иначе он
    # маскирует возврат модалки внутрь оболочки.
    with open(os.path.join(src_dir, "index.css"), encoding="utf-8") as f:
        css = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
    m = re.search(r"\.main-area:has\(([^)]*)\)", css)
    assert m and "modal-overlay" not in m.group(1)


def _frontend(*parts):
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", *parts), encoding="utf-8") as f:
        return f.read()


def _without_comments(css):
    import re
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_content_is_not_capped_at_a_1440px_column():
    """Потолок 1440px писался под ноутбук. На 2560px мониторе контент вставал
    узкой колонкой посередине, а поля по краям выходили шире самой боковой
    панели — замерено: 4 карточки ВМ в ряду вместо 5, которые туда влезают."""
    css = _without_comments(_frontend("index.css"))

    block = css[css.index(".content-container {"):]
    block = block[:block.index("}")]
    assert "max-width: var(--content-max)" in block, "ширина контента снова прибита числом"
    assert "1440px" not in block

    root = css[css.index(":root {"):]
    root = root[:root.index("}")]
    assert "--content-max" in root


def test_header_and_content_share_one_left_edge():
    """Подложка шапки тянется во всю ширину, а её содержимое — нет: иначе на
    широком мониторе заголовок стоял у самого края экрана, тогда как контент
    под ним начинался с середины, и страница переставала читаться как целое.
    Отступ у обоих один и тот же — двумя числами он бы разошёлся."""
    css = _without_comments(_frontend("index.css"))
    src = _frontend("App.jsx")

    assert 'className="top-header-inner"' in src, "содержимому шапки нечем держать сетку"

    inner = css[css.index(".top-header-inner {"):]
    inner = inner[:inner.index("}")]
    assert "max-width: var(--content-max)" in inner
    assert "padding: 0 var(--content-pad)" in inner

    content = css[css.index(".content-container {"):]
    content = content[:content.index("}")]
    assert "var(--content-pad)" in content, "отступы шапки и контента разъедутся"


def test_sidebar_width_comes_from_a_variable():
    """Ширину панели тянет пользователь, и записать её в .sidebar числом
    значит потерять перетаскивание. Мобильный блок переменную намеренно
    игнорирует: там панель — выезжающая шторка, её ширину задаёт не он."""
    css = _without_comments(_frontend("index.css"))
    import re

    block = css[css.index(".sidebar {"):]
    block = block[:block.index("}")]
    assert "width: var(--sidebar-width)" in block
    assert "position: relative" in block, "ручке не от чего позиционироваться"

    mobile = css[css.index("@media (max-width: 768px)"):]
    assert re.search(r"\.sidebar-resizer \{ display: none", mobile), \
        "у шторки нет края, который можно тянуть — ручку там надо прятать"


def test_drag_state_cannot_outlive_the_handle():
    """Класс resizing-sidebar вешается на body и гасит выделение текста на
    всей странице. Если ручку размонтируют посреди перетаскивания — а это
    происходит при переходе на мобильную ширину, — снять класс станет
    некому, и страница останется с курсором col-resize навсегда."""
    src = _frontend("components", "SidebarResizer.jsx")
    assert "useEffect(() => stopDrag" in src, "нет уборки при размонтировании"
    assert "document.body.classList.remove('resizing-sidebar')" in src


def test_sidebar_width_is_clamped_and_persisted():
    """Без нижней границы панель утягивается в полоску, где не прочитать ни
    одного пункта; без верхней — съедает контент. Порог снизу замерен по
    самым длинным пунктам меню, а не выбран на глаз."""
    src = _frontend("components", "SidebarResizer.jsx")
    assert "export const MIN_WIDTH = 252" in src
    assert "Math.min(MAX_WIDTH, Math.max(MIN_WIDTH" in src
    # Запись — в конце перетаскивания, а не на каждый pointermove: иначе за
    # одно движение мыши в хранилище улетают сотни записей.
    assert "writeWidth(safeStorage(), widthRef.current)" in src
    move = src[src.index("const onPointerMove"):src.index("const onPointerUp")]
    assert "writeWidth" not in move


def test_menu_items_never_wrap_to_a_second_line():
    """Панель тянется, и на узких ширинах длинные пункты («Двухфакторная
    защита», «Бэкапы по расписанию») переносились на вторую строку — высота
    строк меню менялась прямо под курсором."""
    css = _without_comments(_frontend("index.css"))
    block = css[css.index(".nav-item {"):]
    block = block[:block.index("}")]
    assert "white-space: nowrap" in block


def test_menu_items_are_not_squeezed_by_a_long_list():
    """overflow у пункта меню и flex-shrink: 0 идут только в паре.
    Автоматический минимальный размер flex-элемента (min-height: auto)
    действует, пока overflow: visible; закрыли overflow — и колонка
    .sidebar-nav получает право сжимать пункты, как только список перестаёт
    влезать в высоту окна. Замерено: 40px → 26px на 1440x900, и тем сильнее,
    чем ниже окно. Список должен прокручиваться, а не ужиматься."""
    css = _without_comments(_frontend("index.css"))
    block = css[css.index(".nav-item {"):]
    block = block[:block.index("}")]
    if "overflow:" in block and "overflow: visible" not in block:
        assert "flex-shrink: 0" in block, "пункты меню снова будет сжимать длина списка"

    nav = css[css.index(".sidebar-nav {"):]
    nav = nav[:nav.index("}")]
    assert "overflow-y: auto" in nav, "сжатие убрали, а прокрутки нет — список просто обрежется"


def test_both_menu_lists_share_one_spacing():
    """Нижний список («Сменить пароль», «Двухфакторная защита», «Выйти») держал
    свой отступ в inline-стилях кнопок. Стоило поменять шаг верхнего — и в
    одной колонке оказывались два разных ритма."""
    css = _without_comments(_frontend("index.css"))
    src = _frontend("App.jsx")

    for rule in (".sidebar-nav {", ".sidebar-footer-nav {"):
        block = css[css.index(rule):]
        block = block[:block.index("}")]
        assert "gap: var(--nav-gap)" in block, f"{rule} задаёт шаг своим числом"

    tail = src[src.index('className="sidebar-footer-nav"'):]
    tail = tail[:tail.index("</aside>")]
    assert "marginBottom" not in tail, "отступ вернулся в inline-стиль кнопки"
