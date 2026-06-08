from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Асинхронный движок для работы с PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=False, 
    pool_pre_ping=True
)

# Фабрика асинхронных сессий
SessionLocal = async_sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine,
    class_=AsyncSession
)

# Базовый класс для моделей SQLAlchemy
Base = declarative_base()

# Зависимость FastAPI для получения асинхронной сессии БД
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
