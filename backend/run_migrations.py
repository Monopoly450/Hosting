import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/aegis")
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql")

engine = create_engine(SYNC_DATABASE_URL)

alter_statements = [
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_read_mbs INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_write_mbs INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_read_iops INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_read_iops INTEGER DEFAULT 0;" if False else "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_write_iops INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS ports_config TEXT;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS firewall_rules TEXT;"
]

with engine.connect() as conn:
    for stmt in alter_statements:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f"Executed: {stmt}")
        except Exception as e:
            print(f"Failed to execute: {stmt}. Error: {e}")
