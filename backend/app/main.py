import os
import logging
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api import vms, host, vnc, images, docker_admin, external_servers, infra, clusters, auth, databases, s3, volumes, snapshots, mail
from app.core.auth import verify_admin_token

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

@app.on_event("startup")
async def startup_event():
    from app.core.database import engine, Base
    from app.models.models import SystemState, AWSSecurityGroup, AWSS3Bucket, AWSIAMUser
    from sqlalchemy import select
    
    logger.info("Инициализация таблиц базы данных...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Таблицы базы данных успешно проверены/созданы.")
    
    # Заполнение начальными данными при пустой БД
    from app.core.database import SessionLocal
    async with SessionLocal() as db:
        # 1. Проверяем настройки системы
        res = await db.execute(select(SystemState).filter_by(id=1))
        if not res.scalars().first():
            db.add(SystemState(id=1, balance=50.0, billing_rate=0.0, ddos_active=False))
            logger.info("Сид: Добавлены начальные настройки system_state.")

        # 2. Проверяем группу безопасности по умолчанию
        res = await db.execute(select(AWSSecurityGroup).filter_by(id="sg-01a2b3c4d"))
        if not res.scalars().first():
            db.add(AWSSecurityGroup(
                id="sg-01a2b3c4d",
                name="default-vpc-sg",
                description="Стандартная группа безопасности VPC",
                rules=[
                    {"type": "Inbound", "protocol": "tcp", "port_range": "22", "source": "0.0.0.0/0"},
                    {"type": "Inbound", "protocol": "tcp", "port_range": "80", "source": "0.0.0.0/0"},
                    {"type": "Inbound", "protocol": "tcp", "port_range": "443", "source": "0.0.0.0/0"},
                    {"type": "Outbound", "protocol": "all", "port_range": "all", "source": "0.0.0.0/0"}
                ],
                bound_instances=["client-my-db-vds", "client-web-app"]
            ))
            logger.info("Сид: Добавлена стандартная группа безопасности sg-01a2b3c4d.")

        # 3. Проверяем дефолтный бакет S3
        res = await db.execute(select(AWSS3Bucket).filter_by(name="aegis-backups-bucket"))
        if not res.scalars().first():
            db.add(AWSS3Bucket(
                name="aegis-backups-bucket",
                region="us-east-1",
                access_policy="Private",
                objects=[
                    {"key": "db-backup-2026-06-07.sql", "size": 154820, "last_update": "2026-06-07 14:02:11"},
                    {"key": "web-config.json", "size": 1242, "last_update": "2026-06-08 09:12:00"}
                ]
            ))
            logger.info("Сид: Добавлен стандартный бакет S3: aegis-backups-bucket.")

        # 4. Проверяем IAM пользователей
        res = await db.execute(select(AWSIAMUser).filter_by(username="admin-operator"))
        if not res.scalars().first():
            db.add(AWSIAMUser(
                username="admin-operator",
                joined_at="2026-06-08 10:00:00",
                policy='{\n  "Version": "2012-10-17",\n  "Statement": [\n    {\n      "Effect": "Allow",\n      "Action": ["ec2:*", "s3:*", "iam:*"],\n      "Resource": "*"\n    }\n  ]\n}'
            ))
            db.add(AWSIAMUser(
                username="dev-developer",
                joined_at="2026-06-08 10:15:00",
                policy='{\n  "Version": "2012-10-17",\n  "Statement": [\n    {\n      "Effect": "Allow",\n      "Action": ["ec2:StartInstance", "ec2:StopInstance", "s3:ListBucket"],\n      "Resource": "*"\n    },\n    {\n      "Effect": "Deny",\n      "Action": ["ec2:TerminateInstance"],\n      "Resource": "*"\n    }\n  ]\n}'
            ))
            logger.info("Сид: Добавлены стандартные IAM-пользователи.")
        
        # 5. Проверяем многопользовательского администратора
        from app.models.models import User
        from app.core.auth import hash_password, ADMIN_TOKEN
        res = await db.execute(select(User).filter_by(username="admin"))
        if not res.scalars().first():
            db.add(User(
                username="admin",
                password_hash=hash_password(ADMIN_TOKEN),
                role="admin",
                max_vcpus=999,
                max_ram_mb=999999,
                max_vms=999,
                max_storage_gb=999999
            ))
            logger.info("Сид: Добавлен дефолтный администратор 'admin'.")
        
        await db.commit()


# Настройка CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Подключение роутеров с валидацией токена
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(vms.router, prefix=f"{settings.API_V1_STR}/vms", tags=["vms"])
app.include_router(clusters.router, prefix=f"{settings.API_V1_STR}/clusters", tags=["clusters"])
app.include_router(databases.router, prefix=f"{settings.API_V1_STR}/databases", tags=["databases"])
app.include_router(s3.router, prefix=f"{settings.API_V1_STR}/s3", tags=["s3"])
app.include_router(volumes.router, prefix=f"{settings.API_V1_STR}/volumes", tags=["volumes"])
app.include_router(snapshots.router, prefix=f"{settings.API_V1_STR}/snapshots", tags=["snapshots"])
app.include_router(mail.router, prefix=f"{settings.API_V1_STR}/mail", tags=["mail"])
app.include_router(host.router, prefix=f"{settings.API_V1_STR}/host", tags=["host"], dependencies=[Depends(verify_admin_token)])
app.include_router(vnc.router, prefix=f"{settings.API_V1_STR}/vnc", tags=["vnc"])
app.include_router(images.router, prefix=f"{settings.API_V1_STR}/images", tags=["images"])
app.include_router(docker_admin.router, prefix=f"{settings.API_V1_STR}/docker", tags=["docker"], dependencies=[Depends(verify_admin_token)])
app.include_router(external_servers.router, prefix=f"{settings.API_V1_STR}/external-servers", tags=["external-servers"], dependencies=[Depends(verify_admin_token)])
app.include_router(infra.router, prefix=f"{settings.API_V1_STR}/infra", tags=["infra"], dependencies=[Depends(verify_admin_token)])

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
