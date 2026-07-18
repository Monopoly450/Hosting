import secrets
import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models.models import ApiToken, User
from app.core.auth import get_current_user, hash_api_token, API_TOKEN_PREFIX

router = APIRouter()


class TokenCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Понятное имя токена")
    expires_days: Optional[int] = Field(None, ge=1, le=3650, description="Срок жизни в днях (без ограничения, если не задан)")


class TokenInfo(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: Optional[str] = None
    last_used: Optional[str] = None
    expires_at: Optional[str] = None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_token(req: TokenCreateRequest, current_user: User = Depends(get_current_user)):
    """Создаёт персональный API-токен. Сам токен показывается ТОЛЬКО ОДИН РАЗ."""
    db = SessionLocal()
    try:
        raw = API_TOKEN_PREFIX + secrets.token_hex(24)  # aeg_<48 hex>
        tok = ApiToken(
            name=req.name.strip(),
            token_prefix=raw[:12],
            token_hash=hash_api_token(raw),
            owner_id=current_user.id,
            expires_at=(datetime.datetime.utcnow() + datetime.timedelta(days=req.expires_days)) if req.expires_days else None,
        )
        db.add(tok)
        db.commit()
        db.refresh(tok)
        return {
            "id": tok.id,
            "name": tok.name,
            "token": raw,   # единственный показ — сохраните его сейчас
            "prefix": tok.token_prefix,
            "expires_at": tok.expires_at.isoformat() if tok.expires_at else None,
        }
    finally:
        db.close()


@router.get("", response_model=List[TokenInfo])
def list_tokens(current_user: User = Depends(get_current_user)):
    """Список токенов текущего пользователя (без самих токенов)."""
    db = SessionLocal()
    try:
        toks = db.query(ApiToken).filter(ApiToken.owner_id == current_user.id).order_by(ApiToken.id.desc()).all()
        return [
            TokenInfo(
                id=t.id, name=t.name, prefix=t.token_prefix + "…",
                created_at=t.created_at.isoformat() if t.created_at else None,
                last_used=t.last_used.isoformat() if t.last_used else None,
                expires_at=t.expires_at.isoformat() if t.expires_at else None,
            ) for t in toks
        ]
    finally:
        db.close()


@router.delete("/{token_id}", status_code=status.HTTP_200_OK)
def revoke_token(token_id: int, current_user: User = Depends(get_current_user)):
    """Отзывает (удаляет) токен. Пользователь может отзывать только свои токены."""
    db = SessionLocal()
    try:
        tok = db.query(ApiToken).filter(ApiToken.id == token_id).first()
        if not tok:
            raise HTTPException(status_code=404, detail="Токен не найден")
        if current_user.role != "admin" and tok.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещён")
        db.delete(tok)
        db.commit()
        return {"status": "revoked"}
    except HTTPException:
        raise
    finally:
        db.close()
