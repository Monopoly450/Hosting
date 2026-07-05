import os
import re
import json
import logging
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from pydantic import BaseModel, Field
from typing import List
from minio import Minio
from app.db import SessionLocal
from app.models.models import User, UserBucket
from app.core.auth import get_current_user
from app.core.crypto import encrypt_secret, decrypt_secret

router = APIRouter()
logger = logging.getLogger("app.api.s3")

class BucketCreateRequest(BaseModel):
    name: str = Field(..., description="Имя бакета (a-z, 0-9, -)")

class BucketResponse(BaseModel):
    id: int
    bucket_name: str
    access_key: str
    secret_key: str
    status: str
    owner_username: str

def get_minio_client():
    return Minio(
        "127.0.0.1:9000",
        access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin-secret-2026"),
        secure=False
    )

@router.post("", response_model=BucketResponse, status_code=status.HTTP_201_CREATED)
def create_bucket(req: BucketCreateRequest, current_user: User = Depends(get_current_user)):
    # Валидация имени бакета (только латинские буквы, цифры и дефис)
    if not re.match(r"^[a-z0-9-]{3,32}$", req.name):
        raise HTTPException(
            status_code=400,
            detail="Имя бакета должно быть длиной от 3 до 32 символов и содержать только латинские буквы, цифры и дефис."
        )

    db = SessionLocal()
    try:
        # Лимит для студентов: макс 3 бакета
        if current_user.role != "admin":
            bucket_count = db.query(UserBucket).filter(UserBucket.owner_id == current_user.id).count()
            if bucket_count >= 3:
                raise HTTPException(status_code=400, detail="Достигнут лимит на создание бакетов (макс. 3).")

        # Префикс к имени бакета
        full_bucket_name = f"{current_user.username}-{req.name}"

        # Проверка уникальности
        existing = db.query(UserBucket).filter(UserBucket.bucket_name == full_bucket_name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Бакет с таким именем уже существует.")

        client = get_minio_client()

        # Создаем бакет в MinIO
        if not client.bucket_exists(full_bucket_name):
            client.make_bucket(full_bucket_name)
        
        # Создаем политику доступа для сервисного аккаунта
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetBucketLocation",
                        "s3:ListBucket",
                        "s3:ListBucketMultipartUploads",
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:DeleteObject",
                        "s3:AbortMultipartUpload"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{full_bucket_name}",
                        f"arn:aws:s3:::{full_bucket_name}/*"
                    ]
                }
            ]
        }

        # Создаем сервисный аккаунт в MinIO с привязкой к этой политике через утилиту mc
        try:
            import subprocess
            import tempfile
            import uuid

            # Генерируем случайные ключи
            access_key = f"ak_{uuid.uuid4().hex[:12]}"
            secret_key = f"sk_{uuid.uuid4().hex[:16]}"

            # Сохраняем политику во временный файл
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as f:
                json.dump(policy, f)
                policy_path = f.name

            try:
                root_user = os.getenv("MINIO_ROOT_USER", "minioadmin")
                root_password = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin-secret-2026")

                # Настраиваем алиас для mc
                subprocess.run([
                    "mc", "alias", "set", "myminio", "http://127.0.0.1:9000",
                    root_user, root_password
                ], capture_output=True, check=True, timeout=10)

                # Создаем service account
                cmd = [
                    "mc", "admin", "user", "svcacct", "add",
                    "--access-key", access_key,
                    "--secret-key", secret_key,
                    "--policy", policy_path,
                    "myminio", root_user
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
                logger.info(f"mc svcacct add success: {res.stdout.strip()}")
            finally:
                try:
                    os.unlink(policy_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Failed to create service account in MinIO via mc: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка генерации ключей S3 в MinIO: {e}")

        # Запись в системную БД
        new_bucket = UserBucket(
            bucket_name=full_bucket_name,
            access_key=access_key,
            secret_key=encrypt_secret(secret_key),
            owner_id=current_user.id
        )
        db.add(new_bucket)
        db.commit()
        db.refresh(new_bucket)

        return BucketResponse(
            id=new_bucket.id,
            bucket_name=new_bucket.bucket_name,
            access_key=new_bucket.access_key,
            secret_key=secret_key,
            status="Active",
            owner_username=current_user.username
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("", response_model=List[BucketResponse])
def list_buckets(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            buckets = db.query(UserBucket).all()
        else:
            buckets = db.query(UserBucket).filter(UserBucket.owner_id == current_user.id).all()

        res = []
        for b in buckets:
            owner = db.query(User).filter(User.id == b.owner_id).first()
            owner_name = owner.username if owner else "Unknown"
            res.append(BucketResponse(
                id=b.id,
                bucket_name=b.bucket_name,
                access_key=b.access_key,
                secret_key=decrypt_secret(b.secret_key),
                status="Active",
                owner_username=owner_name
            ))
        return res
    finally:
        db.close()

@router.delete("/{bucket_id}", status_code=status.HTTP_200_OK)
def delete_bucket(bucket_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        bucket = db.query(UserBucket).filter(UserBucket.id == bucket_id).first()
        if not bucket:
            raise HTTPException(status_code=404, detail="Бакет не найден")

        if current_user.role != "admin" and bucket.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого бакета.")

        client = get_minio_client()

        # 1. Удаляем все файлы внутри бакета (MinIO требует пустой бакет для удаления)
        try:
            if client.bucket_exists(bucket.bucket_name):
                # Находим все объекты
                objects = client.list_objects(bucket.bucket_name, recursive=True)
                for obj in objects:
                    client.remove_object(bucket.bucket_name, obj.object_name)
                # Удаляем сам бакет
                client.remove_bucket(bucket.bucket_name)
        except Exception as e:
            logger.error(f"Failed to delete physical MinIO bucket {bucket.bucket_name}: {e}")

        # 2. Удаляем сервисный аккаунт
        try:
            client.delete_service_account(bucket.access_key)
        except Exception as e:
            logger.error(f"Failed to delete MinIO service account: {e}")

        # 3. Удаляем из системной БД
        db.delete(bucket)
        db.commit()

        return {"status": "Bucket deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("/{bucket_id}/files")
def list_bucket_files(bucket_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        bucket = db.query(UserBucket).filter(UserBucket.id == bucket_id).first()
        if not bucket:
            raise HTTPException(status_code=404, detail="Бакет не найден")
        if current_user.role != "admin" and bucket.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого бакета.")
            
        client = get_minio_client()
        try:
            if not client.bucket_exists(bucket.bucket_name):
                return []
            objects = client.list_objects(bucket.bucket_name, recursive=True)
            return [
                {
                    "name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.strftime("%Y-%m-%d %H:%M:%S") if obj.last_modified else "Unknown"
                }
                for obj in objects
            ]
        except Exception as e:
            logger.error(f"Failed to list objects in MinIO bucket {bucket.bucket_name}: {e}")
            return []
    finally:
        db.close()
        
@router.post("/{bucket_id}/upload")
async def upload_file_to_bucket(bucket_id: int, file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        bucket = db.query(UserBucket).filter(UserBucket.id == bucket_id).first()
        if not bucket:
            raise HTTPException(status_code=404, detail="Бакет не найден")
        if current_user.role != "admin" and bucket.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого бакета.")
            
        client = get_minio_client()
        
        # Читаем файл в память и загружаем в MinIO
        data = await file.read()
        from io import BytesIO
        try:
            client.put_object(
                bucket.bucket_name,
                file.filename,
                BytesIO(data),
                length=len(data),
                content_type=file.content_type
            )
            return {"status": "success", "filename": file.filename}
        except Exception as e:
            logger.error(f"Failed to put object in MinIO bucket {bucket.bucket_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка загрузки файла в MinIO: {e}")
    finally:
        db.close()

@router.delete("/{bucket_id}/files/{filename:path}")
def delete_file_from_bucket(bucket_id: int, filename: str, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        bucket = db.query(UserBucket).filter(UserBucket.id == bucket_id).first()
        if not bucket:
            raise HTTPException(status_code=404, detail="Бакет не найден")
        if current_user.role != "admin" and bucket.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого бакета.")
            
        client = get_minio_client()
        try:
            client.remove_object(bucket.bucket_name, filename)
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Failed to remove object from MinIO bucket {bucket.bucket_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка удаления файла из MinIO: {e}")
    finally:
        db.close()
