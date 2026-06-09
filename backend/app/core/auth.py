import os
from fastapi import HTTPException, status, Security, Depends
from fastapi.security import APIKeyHeader

# Получаем токен из переменных окружения (с дефолтным значением для разработки)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "aegis-admin-secret-key-2026")

# APIKeyHeader автоматически извлекает заголовок X-Admin-Token
token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)

def verify_admin_token(x_admin_token: str = Security(token_header)):
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или отсутствующий токен доступа (X-Admin-Token)",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )
    return x_admin_token
