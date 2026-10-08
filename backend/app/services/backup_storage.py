"""Отдельный приватный S3-бакет резервных копий для каждого владельца."""
import json
import os
import secrets
import subprocess
import tempfile
from datetime import timezone
from minio.error import S3Error
from sqlalchemy import text
from app.models.models import User, UserBucket
from app.core.crypto import encrypt_secret


def bucket_name(owner_id: int) -> str:
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise ValueError("У ресурса нет владельца для S3-бэкапа")
    return f"aegis-backups-u{owner_id}"


def _run_mc(command):
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        # CalledProcessError/TimeoutExpired содержат argv с секретами!
        raise RuntimeError("Не удалось настроить приватный S3-доступ к резервным копиям") from None


def ensure_backup_bucket(db, owner_id: int, s3) -> str:
    name = bucket_name(owner_id)
    # Одна регистрация бакета/ключей при параллельных ручных и плановых копиях.
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 810000000 + owner_id})
    if not db.query(User).filter(User.id == owner_id).first():
        raise ValueError("Владелец ресурса не найден")
    existing = db.query(UserBucket).filter(UserBucket.bucket_name == name).first()
    if existing and (existing.owner_id != owner_id or existing.purpose != "backup"):
        raise ValueError("Имя служебного бакета занято другим ресурсом")
    if not s3.bucket_exists(name):
        s3.make_bucket(name)
    if existing:
        return name
    # MinIO ограничивает сервисные аккаунты: Access Key — 3–20 символов,
    # Secret Key — 8–40. Считаем длину результата, а не исходных байтов.
    access = secrets.token_hex(10)       # 20 символов
    secret = secrets.token_urlsafe(30)  # 40 символов, 240 бит энтропии
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:GetBucketLocation", "s3:ListBucket", "s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{name}", f"arn:aws:s3:::{name}/*"],
        }],
    }
    # Ключи владельца доступны для чтения своих архивов. Запись/удаление
    # выполняются панелью, чтобы не обходить блокировки текущих операций.
    with tempfile.TemporaryDirectory(prefix="aegis-backup-mc-") as config:
        policy_path = os.path.join(config, "policy.json")
        with open(policy_path, "w", encoding="utf-8") as stream:
            json.dump(policy, stream)
        base = ["mc", "--config-dir", config]
        _run_mc(base + [
            "alias", "set", "backup", "http://127.0.0.1:9000",
            os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"],
        ])
        _run_mc(base + [
            "admin", "user", "svcacct", "add", "--access-key", access,
            "--secret-key", secret, "--policy", policy_path,
            "backup", os.environ["MINIO_ROOT_USER"],
        ])
    db.add(UserBucket(
        bucket_name=name, access_key=access, secret_key=encrypt_secret(secret),
        owner_id=owner_id, purpose="backup",
    ))
    db.flush()
    return name


def database_location(user_db):
    return bucket_name(user_db.owner_id), f"databases/{user_db.id}/"


def _legacy_owned(user_db, obj):
    created = user_db.created_at
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return bool(created and obj.last_modified and utc(obj.last_modified) >= utc(created))


def list_database_objects(user_db, s3):
    bucket, prefix = database_location(user_db)
    result = {}
    if s3.bucket_exists(bucket):
        for obj in s3.list_objects(bucket, prefix=prefix, recursive=True):
            result[obj.object_name.rsplit("/", 1)[-1]] = (bucket, obj)
    if s3.bucket_exists("database-backups"):
        for obj in s3.list_objects("database-backups", prefix=f"{user_db.db_name}/", recursive=True):
            if _legacy_owned(user_db, obj):
                result.setdefault(obj.object_name.rsplit("/", 1)[-1], ("database-backups", obj))
    return result


def find_database_object(user_db, filename, s3):
    bucket, prefix = database_location(user_db)
    try:
        s3.stat_object(bucket, prefix + filename)
        return bucket, prefix + filename
    except S3Error as error:
        if error.code not in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
            raise
    key = f"{user_db.db_name}/{filename}"
    obj = s3.stat_object("database-backups", key)
    if not _legacy_owned(user_db, obj):
        raise ValueError("Копия не относится к текущей базе данных")
    return "database-backups", key
