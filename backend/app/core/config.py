import os
from pydantic import field_validator
from pydantic_settings import BaseSettings


def resolve_system_storage_class(value: str | None) -> str:
    """Системные диски ВМ и приватные БД не размещаются в LVM-пуле:
    LVM используется только для подключаемых сетевых дисков."""
    cleaned = (value or "").strip()
    if not cleaned or "lvm" in cleaned.lower() or "vg-" in cleaned.lower():
        return "local-path"
    return cleaned


class Settings(BaseSettings):
    PROJECT_NAME: str = "Antigravity VM Hosting"
    API_V1_STR: str = "/api"
    
    # Хост и порт для запуска FastAPI
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    
    # Настройки Kubernetes
    # Скрипт bootstrap настраивает config в ~/.kube/config
    KUBECONFIG_PATH: str = os.getenv(
        "KUBECONFIG", 
        os.path.expanduser("~/.kube/config")
    )
    STORAGE_CLASS: str = resolve_system_storage_class(os.getenv("STORAGE_CLASS", "local-path"))
    NETWORK_STORAGE_CLASS: str = os.getenv("NETWORK_STORAGE_CLASS", "openebs-lvm")

    @field_validator("STORAGE_CLASS", mode="before")
    @classmethod
    def _normalize_storage_class(cls, value: str | None) -> str:
        return resolve_system_storage_class(value)
    
    # Настройки CORS. По умолчанию "*" (панель отдаётся тем же хостом и
    # авторизуется токеном в заголовке, не куками). Можно ограничить через
    # AEGIS_CORS_ORIGINS="https://panel.example.com,https://vds.example.com".
    BACKEND_CORS_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("AEGIS_CORS_ORIGINS", "*").split(",") if o.strip()
    ]
    
    # URL для подключения к базе данных PostgreSQL
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis"
    )

    class Config:
        case_sensitive = True

settings = Settings()
