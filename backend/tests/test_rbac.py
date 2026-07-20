import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rbac import has_permission, ROLE_RANK, ROLES


def test_admin_can_do_everything():
    for need in ROLES:
        assert has_permission(is_admin=True, is_owner=False, project_role=None, need=need)


def test_owner_can_do_everything_with_own_resource():
    for need in ROLES:
        assert has_permission(is_admin=False, is_owner=True, project_role=None, need=need)


def test_stranger_without_project_role_is_denied():
    for need in ROLES:
        assert not has_permission(is_admin=False, is_owner=False, project_role=None, need=need)


@pytest.mark.parametrize("role,need,expected", [
    # viewer — только чтение
    ("viewer", "viewer", True),
    ("viewer", "editor", False),
    ("viewer", "owner", False),
    # editor — чтение и управление ресурсами, но не участниками
    ("editor", "viewer", True),
    ("editor", "editor", True),
    ("editor", "owner", False),
    # owner — всё в рамках проекта
    ("owner", "viewer", True),
    ("owner", "editor", True),
    ("owner", "owner", True),
])
def test_project_role_matrix(role, need, expected):
    assert has_permission(is_admin=False, is_owner=False, project_role=role, need=need) is expected


def test_viewer_cannot_mutate_this_is_the_key_guarantee():
    """Ключевая гарантия: участник-viewer не может изменять/удалять ресурс,
    даже если он видит его в проекте."""
    assert has_permission(is_admin=False, is_owner=False, project_role="viewer", need="viewer")
    assert not has_permission(is_admin=False, is_owner=False, project_role="viewer", need="editor")


def test_unknown_role_is_denied():
    assert not has_permission(is_admin=False, is_owner=False, project_role="superuser", need="viewer")
    assert not has_permission(is_admin=False, is_owner=False, project_role="", need="viewer")


def test_role_rank_is_strictly_increasing():
    assert ROLE_RANK["viewer"] < ROLE_RANK["editor"] < ROLE_RANK["owner"]


def test_default_need_is_viewer():
    # без явного need достаточно роли viewer
    assert has_permission(is_admin=False, is_owner=False, project_role="viewer")


def test_is_owner_false_when_owner_id_absent():
    """Ресурс без владельца не должен становиться общедоступным."""
    assert not has_permission(is_admin=False, is_owner=False, project_role=None, need="viewer")
