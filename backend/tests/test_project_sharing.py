"""Общий доступ к ресурсам через проекты.

Смысл этих тестов — не в матрице ролей (она в test_rbac.py), а в том, что
каждый тип ресурса действительно подключён к проектам. Раньше вкладка
«Проекты и доступы» была наполовину декоративной: бакет S3 вообще нельзя было
привязать к проекту, а базы и деплои проверяли доступ строго по owner_id —
участник проекта не видел их в списке и получал 403 на любой запрос.

Проверки статические (по исходникам), чтобы не тянуть app.db: он создаёт
движок прямо при импорте и требует psycopg2, которого в окружении может не
быть.
"""
import ast
import io
import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

# Тип ресурса в API -> класс модели.
SHAREABLE = {
    "vm": "VMTask",
    "database": "UserDatabase",
    "deployment": "AppDeployment",
    "bucket": "UserBucket",
}
# Модули, которые обязаны учитывать проекты при проверке доступа.
SHARED_RESOURCE_MODULES = ("s3.py", "databases.py", "vms.py", "deployments.py")
# Модули со списком ресурсов, который должен включать общие ресурсы проекта.
LIST_MODULES = ("s3.py", "databases.py", "deployments.py")


def _src(*parts):
    with io.open(os.path.join(BACKEND, *parts), encoding="utf-8") as f:
        return f.read()


def _api(name):
    return _src("app", "api", name)


@pytest.mark.parametrize("key,model", sorted(SHAREABLE.items()))
def test_resource_type_registered_in_projects_api(key, model):
    """Без записи в RESOURCE_MODELS ресурс нельзя ни привязать к проекту, ни
    посчитать на карточке проекта."""
    src = _api("projects.py")
    assert f'"{key}": {model}' in src, f"{key} не зарегистрирован в RESOURCE_MODELS"


@pytest.mark.parametrize("key,model", sorted(SHAREABLE.items()))
def test_every_shareable_model_has_project_id(key, model):
    """Без колонки project_id ресурс невозможно привязать к проекту, а
    _counts() в projects.py упадёт при первом обращении к списку."""
    tree = ast.parse(_src("app", "models", "models.py"))
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == model), None)
    assert cls is not None, f"модель {model} не найдена"
    fields = {t.id for stmt in cls.body if isinstance(stmt, ast.Assign)
              for t in stmt.targets if isinstance(t, ast.Name)}
    assert "project_id" in fields, f"{model} без project_id"


def test_bucket_project_id_migration_exists():
    """Колонка должна появляться и на уже установленных серверах, а не только
    в свежесозданной схеме."""
    from app.core.migrations import MIGRATION_STATEMENTS

    sql = " ".join(MIGRATION_STATEMENTS).lower()
    assert "alter table user_buckets add column if not exists project_id" in sql


@pytest.mark.parametrize("module", SHARED_RESOURCE_MODULES)
def test_no_owner_only_access_checks_left(module):
    """Проверка вида `owner_id != current_user.id` игнорирует проект — с ней
    общий доступ не работает, как бы ни был настроен проект."""
    bad = [ln.strip() for ln in _api(module).splitlines()
           if "owner_id != current_user.id" in ln]
    assert not bad, "проверка доступа мимо проектов:\n" + "\n".join(bad)


@pytest.mark.parametrize("module", LIST_MODULES)
def test_list_endpoint_includes_project_resources(module):
    """Список должен показывать и то, что отдано в проекты, иначе участник не
    увидит общий ресурс, даже имея на него права."""
    src = _api(module)
    assert "visible_project_ids" in src, f"{module}: список не учитывает проекты"
    assert ".project_id.in_(" in src, f"{module}: нет выборки по проектам"


def _needs(module):
    """Уровень прав каждого эндпоинта: {имя функции: need}."""
    tree = ast.parse(_api(module))
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "require_access":
                for kw in call.keywords:
                    if kw.arg == "need":
                        out[node.name] = kw.value.value
    return out


def test_s3_read_endpoints_require_only_viewer():
    """Наблюдателю должно хватать прав на чтение — иначе роль viewer
    бессмысленна: человек видит бакет в списке, но не может его открыть."""
    needs = _needs("s3.py")
    assert needs.get("list_bucket_files") == "viewer"
    assert needs.get("download_file_from_bucket") == "viewer"
    # А изменяющие — нет: viewer не должен удалять чужие файлы.
    assert needs.get("delete_bucket") == "editor"
    assert needs.get("upload_file_to_bucket") == "editor"
    assert needs.get("delete_file_from_bucket") == "editor"


def test_database_write_endpoints_require_editor():
    """Всё, что меняет базу или её бэкапы, — только для editor и выше."""
    needs = _needs("databases.py")
    for fn in ("delete_database", "bind_database", "execute_sql_query",
               "create_database_backup", "restore_database_backup",
               "delete_database_backup"):
        assert needs.get(fn) == "editor", f"{fn}: need={needs.get(fn)}"
    for fn in ("get_database_metrics", "get_database_tables",
               "list_database_backups", "download_database_backup"):
        assert needs.get(fn) == "viewer", f"{fn}: need={needs.get(fn)}"


def test_deployment_endpoints_have_expected_levels():
    needs = _needs("deployments.py")
    assert needs.get("get_deployment_logs") == "viewer"
    assert needs.get("delete_deployment") == "editor"
    assert needs.get("redeploy_app") == "editor"


def test_shared_resource_access_decision():
    """Сквозная проверка самого решения о доступе для ресурса в проекте."""
    from app.core.rbac import has_permission

    # участник-editor чужого ресурса, лежащего в общем проекте
    assert has_permission(is_admin=False, is_owner=False, project_role="editor", need="editor")
    # тот же человек, но ресурс не в проекте (project_role=None) — доступа нет
    assert not has_permission(is_admin=False, is_owner=False, project_role=None, need="viewer")
