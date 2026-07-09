from typing import List, Optional
from fastapi import APIRouter, Query
from app.db import SessionLocal
from app.models.models import AuditLog

router = APIRouter()


@router.get("")
def list_audit(
    limit: int = Query(200, ge=1, le=1000),
    username: Optional[str] = None,
    action: Optional[str] = None,
    only_failed: bool = False,
):
    """Журнал аудита: последние действия пользователей (кто, когда, откуда, что)."""
    db = SessionLocal()
    try:
        q = db.query(AuditLog)
        if username:
            q = q.filter(AuditLog.username == username)
        if action:
            q = q.filter(AuditLog.action.ilike(f"%{action}%"))
        if only_failed:
            q = q.filter(AuditLog.success == False)  # noqa: E712
        rows = q.order_by(AuditLog.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "username": r.username,
                "ip": r.ip,
                "method": r.method,
                "path": r.path,
                "action": r.action,
                "status_code": r.status_code,
                "success": r.success,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.get("/stats")
def audit_stats():
    """Сводка по журналу: всего событий, ошибок, уникальных пользователей/IP."""
    db = SessionLocal()
    try:
        total = db.query(AuditLog).count()
        failed = db.query(AuditLog).filter(AuditLog.success == False).count()  # noqa: E712
        users = db.query(AuditLog.username).distinct().count()
        ips = db.query(AuditLog.ip).distinct().count()
        return {"total": total, "failed": failed, "users": users, "ips": ips}
    finally:
        db.close()
