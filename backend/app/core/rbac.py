"""RBAC: доступ к ресурсам через членство в проекте.

Модель доступа (аддитивная к прежней):
  • админ — может всё;
  • владелец ресурса — может всё со своим ресурсом (как и раньше);
  • участник проекта, которому принадлежит ресурс, — по своей роли:
      viewer  — только чтение,
      editor  — управление ресурсами,
      owner   — плюс управление участниками проекта.

Ресурсы без project_id остаются личными и ведут себя ровно как раньше.
"""
import logging

from fastapi import HTTPException, status

logger = logging.getLogger("app.core.rbac")

ROLES = ("viewer", "editor", "owner")
ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


def has_permission(*, is_admin: bool, is_owner: bool, project_role, need: str = "viewer") -> bool:
    """Чистая функция решения о доступе — без БД, чтобы её можно было точно протестировать."""
    if is_admin:
        return True
    if is_owner:
        return True
    if not project_role:
        return False
    return ROLE_RANK.get(project_role, 0) >= ROLE_RANK.get(need, ROLE_RANK["viewer"])


def project_role(db, project_id, user_id):
    """Роль пользователя в проекте (или None). Владелец проекта считается owner."""
    if not project_id or not user_id:
        return None
    from app.models.models import Project, ProjectMember

    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj and proj.owner_id == user_id:
        return "owner"
    m = (db.query(ProjectMember)
           .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
           .first())
    return m.role if m else None


def can_access(db, user, resource_owner_id, resource_project_id, need: str = "viewer") -> bool:
    """Решение о доступе к конкретному ресурсу."""
    return has_permission(
        is_admin=(getattr(user, "role", None) == "admin"),
        is_owner=(resource_owner_id is not None and resource_owner_id == user.id),
        project_role=project_role(db, resource_project_id, user.id),
        need=need,
    )


def require_access(db, user, resource_owner_id, resource_project_id, need: str = "viewer",
                   message: str = "Доступ запрещён"):
    if not can_access(db, user, resource_owner_id, resource_project_id, need):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def visible_project_ids(db, user) -> list:
    """Проекты, которые пользователь видит (свои + где он участник)."""
    from app.models.models import Project, ProjectMember

    own = [p.id for p in db.query(Project).filter(Project.owner_id == user.id).all()]
    member = [m.project_id for m in
              db.query(ProjectMember).filter(ProjectMember.user_id == user.id).all()]
    return sorted(set(own) | set(member))
