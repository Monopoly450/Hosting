import os

from sqlalchemy import create_engine, text

from app.core.migrations import MIGRATION_STATEMENTS

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/aegis")
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql")

engine = create_engine(SYNC_DATABASE_URL)

with engine.connect() as conn:
    for stmt in MIGRATION_STATEMENTS:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f"Executed: {stmt.splitlines()[0]}")
        except Exception as e:
            print(f"Failed to execute: {stmt}. Error: {e}")
