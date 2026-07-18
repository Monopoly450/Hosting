"""API управления расписаниями автоматических бэкапов (ВМ и БД)."""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import User, VMTask, UserDatabase, BackupSchedule
from app.core.auth import get_current_user
from app.services.scheduled_backups import compute_next_run

router = APIRouter()
logger = logging.getLogger("app.api.backups")

VALID_FREQ = {"hourly", "daily", "weekly"}


class ScheduleCreate(BaseModel):
    name: str = Field(..., description="Понятное имя расписания")
    target_type: str = Field(..., description="vm или database")
    target_id: int = Field(..., description="ID ВМ или базы данных")
    frequency: str = Field("daily", description="hourly | daily | weekly")
    hour: int = Field(3, ge=0, le=23, description="Час (UTC) для daily/weekly")
    minute: int = Field(0, ge=0, le=59, description="Минута")
    weekday: Optional[int] = Field(None, ge=0, le=6, description="День недели 0=Пн..6=Вс (для weekly)")
    retention: int = Field(7, ge=1, le=365, description="Сколько последних копий хранить")


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    hour: Optional[int] = Field(None, ge=0, le=23)
    minute: Optional[int] = Field(None, ge=0, le=59)
    weekday: Optional[int] = Field(None, ge=0, le=6)
    retention: Optional[int] = Field(None, ge=1, le=365)
    enabled: Optional[bool] = None


class ScheduleInfo(BaseModel):
    id: int
    name: str
    target_type: str
    target_id: int
    target_name: str
    frequency: str
    hour: int
    minute: int
    weekday: Optional[int]
    retention: int
    enabled: bool
    last_run: Optional[str]
    last_status: Optional[str]
    next_run: Optional[str]


def _resolve_target(db, target_type: str, target_id: int, user: User) -> str:
    """Проверяет существование цели и права на неё, возвращает её имя."""
    if target_type == "vm":
        obj = db.query(VMTask).filter(VMTask.id == target_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="ВМ не найдена")
        owner_id, name = obj.owner_id, obj.name
    elif target_type == "database":
        obj = db.query(UserDatabase).filter(UserDatabase.id == target_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="База данных не найдена")
        owner_id, name = obj.owner_id, obj.db_name
    else:
        raise HTTPException(status_code=400, detail="target_type должен быть vm или database")

    if user.role != "admin" and owner_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ к цели запрещён")
    return name


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _to_info(s: BackupSchedule) -> ScheduleInfo:
    return ScheduleInfo(
        id=s.id, name=s.name, target_type=s.target_type, target_id=s.target_id,
        target_name=s.target_name, frequency=s.frequency, hour=s.hour, minute=s.minute,
        weekday=s.weekday, retention=s.retention, enabled=s.enabled,
        last_run=_iso(s.last_run), last_status=s.last_status, next_run=_iso(s.next_run),
    )


@router.get("", response_model=List[ScheduleInfo])
def list_schedules(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        q = db.query(BackupSchedule)
        if current_user.role != "admin":
            q = q.filter(BackupSchedule.owner_id == current_user.id)
        return [_to_info(s) for s in q.order_by(BackupSchedule.id.desc()).all()]
    finally:
        db.close()


@router.post("", response_model=ScheduleInfo, status_code=status.HTTP_201_CREATED)
def create_schedule(req: ScheduleCreate, current_user: User = Depends(get_current_user)):
    if req.frequency not in VALID_FREQ:
        raise HTTPException(status_code=400, detail="frequency должен быть hourly, daily или weekly")

    db = SessionLocal()
    try:
        target_name = _resolve_target(db, req.target_type, req.target_id, current_user)
        weekday = req.weekday if req.frequency == "weekly" else None

        sched = BackupSchedule(
            name=req.name,
            target_type=req.target_type,
            target_id=req.target_id,
            target_name=target_name,
            frequency=req.frequency,
            hour=req.hour,
            minute=req.minute,
            weekday=weekday,
            retention=req.retention,
            enabled=True,
            owner_id=current_user.id,
            next_run=compute_next_run(req.frequency, req.hour, req.minute, weekday),
        )
        db.add(sched)
        db.commit()
        db.refresh(sched)
        return _to_info(sched)
    finally:
        db.close()


def _get_owned(db, schedule_id: int, user: User) -> BackupSchedule:
    sched = db.query(BackupSchedule).filter(BackupSchedule.id == schedule_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Расписание не найдено")
    if user.role != "admin" and sched.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return sched


@router.put("/{schedule_id}", response_model=ScheduleInfo)
def update_schedule(schedule_id: int, req: ScheduleUpdate, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        sched = _get_owned(db, schedule_id, current_user)

        if req.name is not None:
            sched.name = req.name
        if req.frequency is not None:
            if req.frequency not in VALID_FREQ:
                raise HTTPException(status_code=400, detail="Некорректная frequency")
            sched.frequency = req.frequency
        if req.hour is not None:
            sched.hour = req.hour
        if req.minute is not None:
            sched.minute = req.minute
        if req.weekday is not None:
            sched.weekday = req.weekday
        if req.retention is not None:
            sched.retention = req.retention
        if req.enabled is not None:
            sched.enabled = req.enabled

        if sched.frequency != "weekly":
            sched.weekday = None
        # Пересчитываем следующий запуск с учётом новых параметров
        sched.next_run = compute_next_run(sched.frequency, sched.hour, sched.minute, sched.weekday)

        db.commit()
        db.refresh(sched)
        return _to_info(sched)
    finally:
        db.close()


@router.delete("/{schedule_id}", status_code=status.HTTP_200_OK)
def delete_schedule(schedule_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        sched = _get_owned(db, schedule_id, current_user)
        db.delete(sched)
        db.commit()
        return {"status": "deleted", "id": schedule_id}
    finally:
        db.close()


@router.post("/{schedule_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_schedule_now(schedule_id: int, current_user: User = Depends(get_current_user)):
    """Запускает бэкап немедленно (не дожидаясь next_run)."""
    from app.core.k8s_client import K8sClient
    from app.services.scheduled_backups import _execute_one

    db = SessionLocal()
    try:
        sched = _get_owned(db, schedule_id, current_user)
        _execute_one(K8sClient(), db, sched)
        db.refresh(sched)
        return {"status": "done", "last_status": sched.last_status}
    finally:
        db.close()
