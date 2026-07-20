"""API проектов и ролевого доступа (RBAC)."""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import (
    User, Project, ProjectMember, VMTask, UserDatabase, AppDeployment,
)
from app.core.auth import get_current_user
from app.core.rbac import ROLES, project_role, visible_project_ids

router = APIRouter()
logger = logging.getLogger("app.api.projects")

RESOURCE_MODELS = {
    "vm": VMTask,
    "database": UserDatabase,
    "deployment": AppDeployment,
}


class ProjectCreate(BaseModel):
    name: str = Field(..., description="Название проекта")
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class MemberAdd(BaseModel):
    username: str = Field(..., description="Имя пользователя")
    role: str = Field("viewer", description="viewer | editor | owner")


class MemberInfo(BaseModel):
    user_id: int
    username: str
    role: str


class ProjectInfo(BaseModel):
    id: int
    name: str
    description: Optional[str]
    owner_username: str
    my_role: str
    members_count: int
    resources: dict


class ResourceAssign(BaseModel):
    resource_type: str = Field(..., description="vm | database | deployment")
    resource_id: int
    project_id: Optional[int] = Field(None, description="null — открепить от проекта")


def _counts(db, project_id: int) -> dict:
    return {
        key: db.query(model).filter(model.project_id == project_id).count()
        for key, model in RESOURCE_MODELS.items()
    }


def _to_info(db, p: Project, user: User) -> ProjectInfo:
    owner = db.query(User).filter(User.id == p.owner_id).first()
    return ProjectInfo(
        id=p.id, name=p.name, description=p.description,
        owner_username=owner.username if owner else "—",
        my_role=project_role(db, p.id, user.id) or ("admin" if user.role == "admin" else "—"),
        members_count=db.query(ProjectMember).filter(ProjectMember.project_id == p.id).count(),
        resources=_counts(db, p.id),
    )


def _get_project(db, project_id: int, user: User, need: str = "viewer") -> Project:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if user.role == "admin":
        return p
    from app.core.rbac import has_permission
    role = project_role(db, p.id, user.id)
    if not has_permission(is_admin=False, is_owner=False, project_role=role, need=need):
        raise HTTPException(status_code=403, detail="Недостаточно прав в проекте")
    return p


@router.get("", response_model=List[ProjectInfo])
def list_projects(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            projects = db.query(Project).order_by(Project.id.desc()).all()
        else:
            ids = visible_project_ids(db, current_user)
            projects = (db.query(Project).filter(Project.id.in_(ids))
                        .order_by(Project.id.desc()).all() if ids else [])
        return [_to_info(db, p, current_user) for p in projects]
    finally:
        db.close()


@router.post("", response_model=ProjectInfo, status_code=status.HTTP_201_CREATED)
def create_project(req: ProjectCreate, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = Project(name=req.name.strip(), description=req.description, owner_id=current_user.id)
        db.add(p)
        db.commit()
        db.refresh(p)
        # Создатель сразу становится участником с ролью owner
        db.add(ProjectMember(project_id=p.id, user_id=current_user.id, role="owner"))
        db.commit()
        return _to_info(db, p, current_user)
    finally:
        db.close()


@router.put("/{project_id}", response_model=ProjectInfo)
def update_project(project_id: int, req: ProjectUpdate, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = _get_project(db, project_id, current_user, need="owner")
        if req.name is not None:
            p.name = req.name.strip()
        if req.description is not None:
            p.description = req.description
        db.commit()
        db.refresh(p)
        return _to_info(db, p, current_user)
    finally:
        db.close()


@router.delete("/{project_id}", status_code=status.HTTP_200_OK)
def delete_project(project_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = _get_project(db, project_id, current_user, need="owner")
        # Ресурсы не удаляем — только открепляем, чтобы ничего не потерялось
        for model in RESOURCE_MODELS.values():
            db.query(model).filter(model.project_id == p.id).update({model.project_id: None})
        db.query(ProjectMember).filter(ProjectMember.project_id == p.id).delete()
        db.delete(p)
        db.commit()
        return {"status": "deleted", "id": project_id}
    finally:
        db.close()


@router.get("/{project_id}/members", response_model=List[MemberInfo])
def list_members(project_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _get_project(db, project_id, current_user, need="viewer")
        out = []
        for m in db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all():
            u = db.query(User).filter(User.id == m.user_id).first()
            out.append(MemberInfo(user_id=m.user_id, username=u.username if u else "—", role=m.role))
        return out
    finally:
        db.close()


@router.post("/{project_id}/members", response_model=MemberInfo, status_code=status.HTTP_201_CREATED)
def add_member(project_id: int, req: MemberAdd, current_user: User = Depends(get_current_user)):
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Роль должна быть одной из: {', '.join(ROLES)}")
    db = SessionLocal()
    try:
        _get_project(db, project_id, current_user, need="owner")
        user = db.query(User).filter(User.username == req.username.strip()).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        existing = (db.query(ProjectMember)
                    .filter(ProjectMember.project_id == project_id,
                            ProjectMember.user_id == user.id).first())
        if existing:
            existing.role = req.role       # уже участник — просто меняем роль
        else:
            existing = ProjectMember(project_id=project_id, user_id=user.id, role=req.role)
            db.add(existing)
        db.commit()
        return MemberInfo(user_id=user.id, username=user.username, role=req.role)
    finally:
        db.close()


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_200_OK)
def remove_member(project_id: int, user_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = _get_project(db, project_id, current_user, need="owner")
        if user_id == p.owner_id:
            raise HTTPException(status_code=400, detail="Нельзя исключить владельца проекта")
        db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        ).delete()
        db.commit()
        return {"status": "removed", "user_id": user_id}
    finally:
        db.close()


@router.post("/assign", status_code=status.HTTP_200_OK)
def assign_resource(req: ResourceAssign, current_user: User = Depends(get_current_user)):
    """Привязывает ресурс к проекту (или откручивает при project_id=null).
    Требует прав editor в проекте и владения самим ресурсом."""
    model = RESOURCE_MODELS.get(req.resource_type)
    if not model:
        raise HTTPException(status_code=400, detail="resource_type: vm | database | deployment")

    db = SessionLocal()
    try:
        obj = db.query(model).filter(model.id == req.resource_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="Ресурс не найден")
        if current_user.role != "admin" and obj.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Вы не владелец этого ресурса")

        if req.project_id is not None:
            _get_project(db, req.project_id, current_user, need="editor")

        obj.project_id = req.project_id
        db.commit()
        return {"status": "ok", "resource_type": req.resource_type,
                "resource_id": req.resource_id, "project_id": req.project_id}
    finally:
        db.close()
