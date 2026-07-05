import os
import base64
import hmac
import hashlib
import json
import time
from fastapi import HTTPException, status, Security, Depends
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.models.models import User

# Получаем токен из переменных окружения
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    raise ValueError("Критическая ошибка безопасности: Переменная окружения ADMIN_TOKEN не задана!")
if ADMIN_TOKEN == "aegis-admin-secret-key-2026":
    raise ValueError("Критическая ошибка безопасности: Использование стандартного ADMIN_TOKEN 'aegis-admin-secret-key-2026' запрещено!")

# Заголовки для авторизации
token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)
security_bearer = HTTPBearer(auto_error=False)

# --- УТИЛИТЫ БЕЗОПАСНОСТИ (Без внешних зависимостей) ---

def hash_password(password: str) -> str:
    """Хэширует пароль с помощью PBKDF2-HMAC-SHA256"""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + ":" + key.hex()

def verify_password(password: str, hashed: str) -> bool:
    """Проверяет пароль против хэша"""
    try:
        salt_hex, key_hex = hashed.split(":")
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(key, new_key)
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: int = 3600 * 24) -> str:
    """Создает HMAC-SHA256 подписанный токен доступа (аналог JWT)"""
    payload = data.copy()
    payload["exp"] = time.time() + expires_delta
    payload_str = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(ADMIN_TOKEN.encode(), payload_str.encode(), hashlib.sha256).digest()
    sig_str = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload_str}.{sig_str}"

def decode_access_token(token: str) -> dict:
    """Декодирует и верифицирует токен"""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_str, sig_str = parts
        
        # Верификация подписи
        expected_sig = hmac.new(ADMIN_TOKEN.encode(), payload_str.encode(), hashlib.sha256).digest()
        expected_sig_str = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")
        if not hmac.compare_digest(sig_str, expected_sig_str):
            return None
            
        # Восстановление паддинга для Base64
        rem = len(payload_str) % 4
        if rem > 0:
            payload_str += "=" * (4 - rem)
            
        payload = json.loads(base64.urlsafe_b64decode(payload_str.encode()).decode())
        if payload.get("exp", 0) < time.time():
            return None  # Токен истек
        return payload
    except Exception:
        return None

# --- ЗАВИСИМОСТИ FASTAPI ---

async def get_db():
    async with SessionLocal() as session:
        yield session

async def verify_admin_token(
    x_admin_token: str = Security(token_header),
    credentials: HTTPAuthorizationCredentials = Depends(security_bearer),
    db: AsyncSession = Depends(get_db)
):
    # 1. Проверяем прямой X-Admin-Token (для старых клиентов и оркестратора)
    if x_admin_token and x_admin_token == ADMIN_TOKEN:
        return x_admin_token

    # 2. Проверяем JWT Bearer токен (для вошедшего в веб-панель админа)
    if credentials:
        payload = decode_access_token(credentials.credentials)
        if payload and "sub" in payload:
            username = payload["sub"]
            res = await db.execute(select(User).filter_by(username=username))
            user = res.scalars().first()
            if user and user.role == "admin":
                return credentials.credentials

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный или отсутствующий токен доступа",
        headers={"WWW-Authenticate": "Bearer or X-Admin-Token"},
    )

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_bearer),
    x_admin_token: str = Security(token_header),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Извлекает текущего пользователя из JWT Bearer токена или X-Admin-Token"""
    
    # 1. Если передан системный X-Admin-Token (например, от оркестратора или админа)
    if x_admin_token and x_admin_token == ADMIN_TOKEN:
        # Ищем или создаем виртуального суперпользователя admin
        res = await db.execute(select(User).filter_by(username="admin"))
        admin_user = res.scalars().first()
        if not admin_user:
            admin_user = User(
                username="admin",
                password_hash=hash_password("admin-system-fallback-pass"),
                role="admin",
                max_vcpus=999,
                max_ram_mb=999999,
                max_vms=999,
                max_storage_gb=99999
            )
            db.add(admin_user)
            await db.commit()
            await db.refresh(admin_user)
        return admin_user

    # 2. Обычная авторизация по Bearer токену
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или истекший сессионный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    username = payload["sub"]
    res = await db.execute(select(User).filter_by(username=username))
    user = res.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def check_admin(current_user: User = Depends(get_current_user)) -> User:
    """Убеждается, что текущий пользователь является администратором"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для выполнения операции (требуется роль admin)"
        )
    return current_user
