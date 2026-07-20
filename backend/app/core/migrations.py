"""Единый список идемпотентных миграций схемы БД.

Используется и стартовым хуком FastAPI (main.py), и скриптом run_migrations.py,
чтобы набор ALTER-выражений не расходился между ними.
"""
import logging

from sqlalchemy import text

logger = logging.getLogger("app.core.migrations")

MIGRATION_STATEMENTS = [
    # vm_tasks
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS iso_url VARCHAR;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS owner_id INTEGER;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS cluster_id INTEGER;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_read_mbs INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_write_mbs INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_read_iops INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS disk_write_iops INTEGER DEFAULT 0;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS ports_config VARCHAR;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS firewall_rules VARCHAR;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS cloud_init_template VARCHAR;",
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS custom_user_data TEXT;",
    # Переименования старых колонок
    """DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_databases' AND column_name='name') THEN
            ALTER TABLE user_databases RENAME COLUMN name TO db_name;
        END IF;
    END $$;""",
    """DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_buckets' AND column_name='name') THEN
            ALTER TABLE user_buckets RENAME COLUMN name TO bucket_name;
        END IF;
    END $$;""",
    # owner_id для пользовательских ресурсов
    "ALTER TABLE user_databases ADD COLUMN IF NOT EXISTS owner_id INTEGER;",
    "ALTER TABLE user_buckets ADD COLUMN IF NOT EXISTS owner_id INTEGER;",
    "ALTER TABLE user_volumes ADD COLUMN IF NOT EXISTS owner_id INTEGER;",
    "ALTER TABLE user_mailboxes ADD COLUMN IF NOT EXISTS owner_id INTEGER;",
    "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS owner_id INTEGER;",
    # SSH bastion / jump host для внешних серверов
    "ALTER TABLE external_servers ADD COLUMN IF NOT EXISTS bastion_host VARCHAR;",
    "ALTER TABLE external_servers ADD COLUMN IF NOT EXISTS bastion_port INTEGER DEFAULT 22;",
    "ALTER TABLE external_servers ADD COLUMN IF NOT EXISTS bastion_username VARCHAR;",
    "ALTER TABLE external_servers ADD COLUMN IF NOT EXISTS bastion_password VARCHAR;",
    # SSH-ключи для ВМ
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS ssh_key VARCHAR;",
    # Стабильный IP на мосту br-vms
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS static_ip VARCHAR;",
    # Проекты (RBAC): привязка ресурсов к проекту
    "ALTER TABLE vm_tasks ADD COLUMN IF NOT EXISTS project_id INTEGER;",
    "ALTER TABLE user_databases ADD COLUMN IF NOT EXISTS project_id INTEGER;",
    "ALTER TABLE app_deployments ADD COLUMN IF NOT EXISTS project_id INTEGER;",
    # Двухфакторная аутентификация (TOTP)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_backup_codes TEXT;",
]


async def apply_migrations(conn):
    """Применяет миграции в рамках открытого async-соединения SQLAlchemy."""
    for stmt in MIGRATION_STATEMENTS:
        try:
            await conn.execute(text(stmt))
        except Exception as e:
            logger.warning(f"Миграция не применилась ({stmt.splitlines()[0]}...): {e}")


async def encrypt_legacy_secrets(db):
    """Разовая миграция данных: шифрует секреты, сохранённые в открытом виде
    до внедрения app.core.crypto."""
    from sqlalchemy import select
    from app.core.crypto import encrypt_secret, is_encrypted
    from app.models.models import ExternalServer, UserDatabase, UserBucket

    encrypted = 0
    for model, field in ((ExternalServer, "password"), (UserDatabase, "db_password"), (UserBucket, "secret_key")):
        res = await db.execute(select(model))
        for row in res.scalars().all():
            value = getattr(row, field)
            if value and not is_encrypted(value):
                setattr(row, field, encrypt_secret(value))
                encrypted += 1
    if encrypted:
        await db.commit()
        logger.info(f"Зашифровано {encrypted} секретов, хранившихся в открытом виде.")
