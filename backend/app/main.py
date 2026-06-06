import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api import vms, host, vnc, images, docker_admin

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("app.main")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Монтируем раздачу образов
IMAGES_DIR = os.getenv("IMAGES_DIR", "/app/data/images")
os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/static/images", StaticFiles(directory=IMAGES_DIR), name="static-images")

# Настройка CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Подключение роутеров
app.include_router(vms.router, prefix=f"{settings.API_V1_STR}/vms", tags=["vms"])
app.include_router(host.router, prefix=f"{settings.API_V1_STR}/host", tags=["host"])
app.include_router(vnc.router, prefix=f"{settings.API_V1_STR}/vnc", tags=["vnc"])
app.include_router(images.router, prefix=f"{settings.API_V1_STR}/images", tags=["images"])
app.include_router(docker_admin.router, prefix=f"{settings.API_V1_STR}/docker", tags=["docker"])

@app.get("/")
def read_root():
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Запуск FastAPI сервера на {settings.HOST}:{settings.PORT}...")
    uvicorn.run(
        "main:app", 
        host=settings.HOST, 
        port=settings.PORT, 
        reload=True
    )
