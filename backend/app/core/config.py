import os
from pydantic_settings import BaseSettings

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
    
    # Настройки CORS
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    
    # URL для подключения к базе данных PostgreSQL
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis"
    )

    class Config:
        case_sensitive = True

settings = Settings()
