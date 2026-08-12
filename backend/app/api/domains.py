"""API своих доменов с автоматическим TLS через Caddy."""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import User, Domain, AppDeployment, VMTask
from app.core.auth import get_current_user
from app.core.docker_client import HostDockerClient
from app.core.netutils import host_for_links
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
    ownership_ok: bool
    challenge_record: str          # имя TXT-записи, которую нужно создать
    verification_token: Optional[str]
    last_error: Optional[str]
    last_checked: Optional[str]
    url: str


def _to_info(d: Domain) -> DomainInfo:
    return DomainInfo(
        id=d.id, domain=d.domain, target_type=d.target_type, target_id=d.target_id,
        target_port=d.target_port, status=d.status or "pending", dns_ok=bool(d.dns_ok),
        ownership_ok=bool(d.ownership_ok),
        challenge_record=dsvc.challenge_record_name(d.domain),
        verification_token=d.verification_token,
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
def status_(request: Request, current_user: User = Depends(get_current_user)):
    """Статус прокси и данные для настройки DNS."""
    st = dsvc.caddy_status(_docker(), host=host_for_links(request))
    st["acme_email"] = dsvc.acme_email()
    # Домены служебных сервисов: их задают в .env, а не в БД, поэтому иначе
    # интерфейс о них не узнает. Нужны, чтобы почта и хранилище показывали
    # реальный адрес вместо IP с портом (см. MailPanel, S3Panel).
    #
    # Собираем из таблицы SYSTEM_SERVICES, а не перечисляем по одному: раньше
    # добавление сервиса требовало не забыть про это место, и оно отставало.
    domains = dsvc.system_domains()
    st.update(domains)
    # Описание сервисов — чтобы интерфейс мог показать список без своей копии
    st["system_services"] = [
        {"key": env.lower(), "label": label, "domain": domains.get(env.lower(), "")}
        for env, _upstream, label in dsvc.SYSTEM_SERVICES
    ]
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
            ownership_ok=False, verification_token=dsvc.generate_verification_token(),
        )
        db.add(dom)
        db.commit()
        db.refresh(dom)
        return _to_info(dom)
    finally:
        db.close()


@router.post("/{domain_id}/verify")
def verify_domain(domain_id: int, request: Request, current_user: User = Depends(get_current_user)):
    """Проверяет A-запись и, если всё верно, включает домен в конфиг Caddy
    (после этого Caddy сам выпустит сертификат Let's Encrypt)."""
    db = SessionLocal()
    try:
        dom = _owned(db, domain_id, current_user)

        # Тот же адрес, что панель показывает в подсказке «A @ → ...». Если
        # сверять с другим, пользователь пропишет ровно то, что ему показали,
        # а проверка всё равно не пройдёт.
        expected = host_for_links(request)

        # 1) Владение доменом (TXT), 2) маршрутизация (A-запись).
        # Порядок важен: пока владение не доказано, домен в конфиг не попадает,
        # даже если A-запись уже указывает на этот сервер.
        own_ok, own_detail = dsvc.check_ownership(dom.domain, dom.verification_token)
        dns_ok, dns_detail = dsvc.check_dns(dom.domain, expected_ip=expected)

        dom.ownership_ok = own_ok
        dom.dns_ok = dns_ok
        dom.last_checked = datetime.utcnow()
        ready = own_ok and dns_ok
        dom.status = "active" if ready else "pending"
        dom.last_error = None if ready else (own_detail if not own_ok else dns_detail)
        db.commit()

        applied = _apply_config(db) if ready else {
            "applied": False,
            "reason": "Владение доменом не подтверждено" if not own_ok else "DNS не подтверждён",
        }
        db.refresh(dom)
        return {
            "ownership_ok": own_ok, "ownership_detail": own_detail,
            "dns_ok": dns_ok, "detail": dns_detail,
            "expected_ip": expected,
            "challenge_record": dsvc.challenge_record_name(dom.domain),
            "verification_token": dom.verification_token,
            **applied,
        }
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
