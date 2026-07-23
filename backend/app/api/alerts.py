"""API алертов: каналы уведомлений и правила оповещения."""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import User, VMTask, NotificationChannel, AlertRule
from app.core.auth import get_current_user
from app.core.crypto import encrypt_secret, decrypt_secret
from app.services.alerts import METRIC_CATALOG, NUMERIC_METRICS

router = APIRouter()
logger = logging.getLogger("app.api.alerts")

VALID_CHANNEL_TYPES = {"webhook", "telegram"}


# ------------------------------- Каналы -------------------------------------

class ChannelCreate(BaseModel):
    name: str
    type: str = Field(..., description="webhook | telegram")
    config: dict = Field(..., description="webhook: {url}; telegram: {bot_token, chat_id}")


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    enabled: Optional[bool] = None


class ChannelInfo(BaseModel):
    id: int
    name: str
    type: str
    summary: str          # безопасное представление без секретов
    enabled: bool


def _channel_summary(ctype: str, cfg: dict) -> str:
    if ctype == "webhook":
        url = cfg.get("url", "")
        # Прячем query-часть (может содержать токен)
        return url.split("?")[0] if url else "webhook"
    if ctype == "telegram":
        chat = cfg.get("chat_id", "?")
        return f"Telegram → chat {chat}"
    return ctype


def _validate_channel_config(ctype: str, cfg: dict):
    if ctype == "webhook":
        from app.core.ssrf import validate_public_url
        try:
            validate_public_url(cfg.get("url", ""))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"webhook: {e}")
    elif ctype == "telegram":
        if not cfg.get("bot_token") or not cfg.get("chat_id"):
            raise HTTPException(status_code=400, detail="telegram: нужны bot_token и chat_id")


def _channel_to_info(ch: NotificationChannel) -> ChannelInfo:
    try:
        cfg = json.loads(decrypt_secret(ch.config))
    except Exception:
        cfg = {}
    return ChannelInfo(id=ch.id, name=ch.name, type=ch.type,
                       summary=_channel_summary(ch.type, cfg), enabled=ch.enabled)


def _owned_channel(db, channel_id: int, user: User) -> NotificationChannel:
    ch = db.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден")
    if user.role != "admin" and ch.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return ch


@router.get("/channels", response_model=List[ChannelInfo])
def list_channels(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        q = db.query(NotificationChannel)
        if current_user.role != "admin":
            q = q.filter(NotificationChannel.owner_id == current_user.id)
        return [_channel_to_info(c) for c in q.order_by(NotificationChannel.id.desc()).all()]
    finally:
        db.close()


@router.post("/channels", response_model=ChannelInfo, status_code=status.HTTP_201_CREATED)
def create_channel(req: ChannelCreate, current_user: User = Depends(get_current_user)):
    if req.type not in VALID_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail="type должен быть webhook или telegram")
    _validate_channel_config(req.type, req.config)
    db = SessionLocal()
    try:
        ch = NotificationChannel(
            name=req.name, type=req.type,
            config=encrypt_secret(json.dumps(req.config)),
            enabled=True, owner_id=current_user.id,
        )
        db.add(ch)
        db.commit()
        db.refresh(ch)
        return _channel_to_info(ch)
    finally:
        db.close()


@router.put("/channels/{channel_id}", response_model=ChannelInfo)
def update_channel(channel_id: int, req: ChannelUpdate, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        ch = _owned_channel(db, channel_id, current_user)
        if req.name is not None:
            ch.name = req.name
        if req.config is not None:
            _validate_channel_config(ch.type, req.config)
            ch.config = encrypt_secret(json.dumps(req.config))
        if req.enabled is not None:
            ch.enabled = req.enabled
        db.commit()
        db.refresh(ch)
        return _channel_to_info(ch)
    finally:
        db.close()


@router.delete("/channels/{channel_id}", status_code=status.HTTP_200_OK)
def delete_channel(channel_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        ch = _owned_channel(db, channel_id, current_user)
        # Отвязываем правила, чтобы не осталось «висячих» ссылок
        db.query(AlertRule).filter(AlertRule.channel_id == ch.id).update({AlertRule.channel_id: None})
        db.delete(ch)
        db.commit()
        return {"status": "deleted", "id": channel_id}
    finally:
        db.close()


@router.post("/channels/{channel_id}/test", status_code=status.HTTP_202_ACCEPTED)
def test_channel(channel_id: int, current_user: User = Depends(get_current_user)):
    """Отправляет тестовое сообщение в канал."""
    from app.services.alerts import _http_post_json
    db = SessionLocal()
    try:
        ch = _owned_channel(db, channel_id, current_user)
        cfg = json.loads(decrypt_secret(ch.config))
        text = f"✅ Тестовое уведомление от Aegis (канал «{ch.name}»)."
        try:
            if ch.type == "telegram":
                _http_post_json(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                                {"chat_id": cfg["chat_id"], "text": text})
            else:
                _http_post_json(cfg["url"], {"state": "test", "text": text})
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Не удалось доставить: {e}")
        return {"status": "sent"}
    finally:
        db.close()


# ------------------------------- Правила ------------------------------------

class RuleCreate(BaseModel):
    name: str
    target_type: str = Field(..., description="vm | host")
    target_id: Optional[int] = Field(None, description="ID ВМ (для host не нужен)")
    metric: str = Field(..., description="status | cpu_percent | memory_percent")
    comparator: str = Field(">", description="> | <")
    threshold: Optional[float] = Field(None, description="Порог (не нужен для metric=status)")
    channel_id: Optional[int] = None


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    comparator: Optional[str] = None
    threshold: Optional[float] = None
    channel_id: Optional[int] = None
    enabled: Optional[bool] = None


class RuleInfo(BaseModel):
    id: int
    name: str
    target_type: str
    target_id: Optional[int]
    target_name: str
    metric: str
    comparator: str
    threshold: Optional[float]
    channel_id: Optional[int]
    enabled: bool
    state: str
    last_value: Optional[float]
    last_checked: Optional[str]
    last_error: Optional[str]


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _rule_to_info(r: AlertRule) -> RuleInfo:
    return RuleInfo(
        id=r.id, name=r.name, target_type=r.target_type, target_id=r.target_id,
        target_name=r.target_name, metric=r.metric, comparator=r.comparator,
        threshold=r.threshold, channel_id=r.channel_id, enabled=r.enabled,
        state=r.state or "ok", last_value=r.last_value,
        last_checked=_iso(r.last_checked), last_error=r.last_error,
    )


def _owned_rule(db, rule_id: int, user: User) -> AlertRule:
    r = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    if user.role != "admin" and r.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return r


@router.get("/rules", response_model=List[RuleInfo])
def list_rules(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        q = db.query(AlertRule)
        if current_user.role != "admin":
            q = q.filter(AlertRule.owner_id == current_user.id)
        return [_rule_to_info(r) for r in q.order_by(AlertRule.id.desc()).all()]
    finally:
        db.close()


@router.post("/rules", response_model=RuleInfo, status_code=status.HTTP_201_CREATED)
def create_rule(req: RuleCreate, current_user: User = Depends(get_current_user)):
    if req.target_type not in METRIC_CATALOG:
        raise HTTPException(status_code=400, detail="target_type должен быть vm или host")
    if req.metric not in METRIC_CATALOG[req.target_type]:
        raise HTTPException(status_code=400, detail=f"Метрика {req.metric} недоступна для {req.target_type}")
    if req.metric in NUMERIC_METRICS:
        if req.threshold is None:
            raise HTTPException(status_code=400, detail="Для этой метрики нужен threshold")
        if req.comparator not in (">", "<"):
            raise HTTPException(status_code=400, detail="comparator должен быть > или <")

    db = SessionLocal()
    try:
        # Определяем цель
        if req.target_type == "vm":
            if not req.target_id:
                raise HTTPException(status_code=400, detail="Для ВМ нужен target_id")
            vm = db.query(VMTask).filter(VMTask.id == req.target_id).first()
            if not vm:
                raise HTTPException(status_code=404, detail="ВМ не найдена")
            if current_user.role != "admin" and vm.owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="Доступ к ВМ запрещён")
            target_name = vm.name
        else:
            target_name = "host"
            if current_user.role != "admin":
                raise HTTPException(status_code=403, detail="Алерты по хосту доступны только администратору")

        # Проверяем канал, если задан
        if req.channel_id is not None:
            _owned_channel(db, req.channel_id, current_user)

        rule = AlertRule(
            name=req.name, target_type=req.target_type,
            target_id=req.target_id if req.target_type == "vm" else None,
            target_name=target_name, metric=req.metric,
            comparator=req.comparator, threshold=req.threshold,
            channel_id=req.channel_id, enabled=True, owner_id=current_user.id, state="ok",
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return _rule_to_info(rule)
    finally:
        db.close()


@router.put("/rules/{rule_id}", response_model=RuleInfo)
def update_rule(rule_id: int, req: RuleUpdate, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rule = _owned_rule(db, rule_id, current_user)
        if req.name is not None:
            rule.name = req.name
        if req.comparator is not None:
            if req.comparator not in (">", "<"):
                raise HTTPException(status_code=400, detail="comparator должен быть > или <")
            rule.comparator = req.comparator
        if req.threshold is not None:
            rule.threshold = req.threshold
        if req.channel_id is not None:
            _owned_channel(db, req.channel_id, current_user)
            rule.channel_id = req.channel_id
        if req.enabled is not None:
            rule.enabled = req.enabled
        db.commit()
        db.refresh(rule)
        return _rule_to_info(rule)
    finally:
        db.close()


@router.delete("/rules/{rule_id}", status_code=status.HTTP_200_OK)
def delete_rule(rule_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rule = _owned_rule(db, rule_id, current_user)
        db.delete(rule)
        db.commit()
        return {"status": "deleted", "id": rule_id}
    finally:
        db.close()
