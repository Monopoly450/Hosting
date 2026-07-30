from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Асинхронный движок для работы с PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=False, 
    pool_pre_ping=True
)

# Фабрика асинхронных сессий.
#
# expire_on_commit=False принципиально важен для async-сессии. По умолчанию
# SQLAlchemy после commit() помечает объекты устаревшими, и первое же обращение
# к атрибуту тянет SELECT для обновления. В асинхронном режиме такой неявный
# запрос происходит вне greenlet-контекста и падает:
#
#   MissingGreenlet: greenlet_spawn has not been called;
#   can't call await_only() here
#
# Ломалось всё, где после commit читается поле объекта: настройка 2FA
# (обращение к current_user.username) и вход по резервному коду (расход кода
# делает commit, после которого читается user.username для выдачи токена).
SessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
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
