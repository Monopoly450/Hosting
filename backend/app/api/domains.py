"""API своих доменов с автоматическим TLS через Caddy."""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import User, Domain, AppDeployment, VMTask
from app.core.auth import get_current_user
from app.core.docker_client import HostDockerClient
from app.services import domains as dsvc

router = APIRouter()
logger = logging.getLogger("app.api.domains")


def _docker():
    c = HostDockerClient()
    c.connect()
    return c


def _k8s():
    from app.core.k8s_client import K8sClient
    return K8sClient()


class DomainCreate(BaseModel):
    domain: str = Field(..., description="Полное доменное имя, напр. app.example.com")
    target_type: str = Field("deployment", description="deployment | vm")
    target_id: int = Field(..., description="ID деплоя или ВМ")
    target_port: Optional[int] = Field(None, ge=1, le=65535,
                                       description="Внутренний порт (для деплоя берётся автоматически)")


class DomainInfo(BaseModel):
    id: int
    domain: str
    target_type: str
    target_id: int
    target_port: int
    status: str
    dns_ok: bool
    last_error: Optional[str]
    last_checked: Optional[str]
    url: str


def _to_info(d: Domain) -> DomainInfo:
    return DomainInfo(
        id=d.id, domain=d.domain, target_type=d.target_type, target_id=d.target_id,
        target_port=d.target_port, status=d.status or "pending", dns_ok=bool(d.dns_ok),
        last_error=d.last_error, last_checked=d.last_checked.isoformat() if d.last_checked else None,
        url=f"https://{d.domain}",
    )


def _owned(db, domain_id: int, user: User) -> Domain:
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Домен не найден")
    if user.role != "admin" and d.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return d


def _apply_config(db):
    """Пересобирает Caddyfile из активных доменов и применяет его.

    Никогда не бросает исключение: применение конфига — побочный эффект
    добавления/удаления домена, и его сбой не должен ронять сам запрос.
    """
    try:
        docker_client = _docker()
        if not docker_client.is_available():
            return {"applied": False, "reason": "Docker недоступен"}
        entries = dsvc.build_entries(db, _k8s())
        caddyfile = dsvc.build_caddyfile(entries, dsvc.acme_email())
    except Exception as e:
        logger.error(f"Не удалось собрать конфиг Caddy: {e}")
        return {"applied": False, "reason": str(e)}
    try:
        dsvc.ensure_caddy(docker_client, caddyfile)
        return {"applied": True, "sites": len(entries)}
    except Exception as e:
        logger.error(f"Не удалось применить конфиг Caddy: {e}")
        return {"applied": False, "reason": str(e)}


@router.get("/status")
def status_(current_user: User = Depends(get_current_user)):
    """Статус прокси и данные для настройки DNS."""
    st = dsvc.caddy_status(_docker())
    st["acme_email"] = dsvc.acme_email()
    return st


@router.get("", response_model=List[DomainInfo])
def list_domains(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        q = db.query(Domain)
        if current_user.role != "admin":
            q = q.filter(Domain.owner_id == current_user.id)
        return [_to_info(d) for d in q.order_by(Domain.id.desc()).all()]
    finally:
        db.close()


@router.post("", response_model=DomainInfo, status_code=status.HTTP_201_CREATED)
def create_domain(req: DomainCreate, current_user: User = Depends(get_current_user)):
    name = req.domain.strip().lower().rstrip(".")
    if not dsvc.is_valid_domain(name):
        raise HTTPException(status_code=400, detail="Некорректное доменное имя")
    if req.target_type not in ("deployment", "vm"):
        raise HTTPException(status_code=400, detail="target_type должен быть deployment или vm")

    db = SessionLocal()
    try:
        if db.query(Domain).filter(Domain.domain == name).first():
            raise HTTPException(status_code=400, detail="Такой домен уже добавлен")

        # Проверяем цель и права на неё, определяем порт
        if req.target_type == "deployment":
            dep = db.query(AppDeployment).filter(AppDeployment.id == req.target_id).first()
            if not dep:
                raise HTTPException(status_code=404, detail="Деплой не найден")
            if current_user.role != "admin" and dep.owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="Доступ к деплою запрещён")
            port = req.target_port or dep.app_port
        else:
            vm = db.query(VMTask).filter(VMTask.id == req.target_id).first()
            if not vm:
                raise HTTPException(status_code=404, detail="ВМ не найдена")
            if current_user.role != "admin" and vm.owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="Доступ к ВМ запрещён")
            if not req.target_port:
                raise HTTPException(status_code=400, detail="Для ВМ укажите target_port")
            port = req.target_port

        dom = Domain(
            domain=name, target_type=req.target_type, target_id=req.target_id,
            target_port=port, owner_id=current_user.id, status="pending", dns_ok=False,
        )
        db.add(dom)
        db.commit()
        db.refresh(dom)
        return _to_info(dom)
    finally:
        db.close()


@router.post("/{domain_id}/verify")
def verify_domain(domain_id: int, current_user: User = Depends(get_current_user)):
    """Проверяет A-запись и, если всё верно, включает домен в конфиг Caddy
    (после этого Caddy сам выпустит сертификат Let's Encrypt)."""
    db = SessionLocal()
    try:
        dom = _owned(db, domain_id, current_user)
        ok, detail = dsvc.check_dns(dom.domain)
        dom.dns_ok = ok
        dom.last_checked = datetime.utcnow()
        dom.last_error = None if ok else detail
        dom.status = "active" if ok else "pending"
        db.commit()

        applied = _apply_config(db) if ok else {"applied": False, "reason": "DNS не подтверждён"}
        db.refresh(dom)
        return {"dns_ok": ok, "detail": detail, "expected_ip": dsvc.host_ip(), **applied}
    finally:
        db.close()


@router.post("/reapply")
def reapply(current_user: User = Depends(get_current_user)):
    """Пересобрать и применить конфиг (например, после смены IP ВМ)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Только для администратора")
    db = SessionLocal()
    try:
        return _apply_config(db)
    finally:
        db.close()


@router.delete("/{domain_id}", status_code=status.HTTP_200_OK)
def delete_domain(domain_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        dom = _owned(db, domain_id, current_user)
        db.delete(dom)
        db.commit()
        _apply_config(db)
        return {"status": "deleted", "id": domain_id}
    finally:
        db.close()
