import re
import string
import secrets
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.db import SessionLocal
from app.models.models import User, UserDatabase, VMTask
from app.core.auth import get_current_user
from app.core.crypto import encrypt_secret, decrypt_secret

router = APIRouter()
logger = logging.getLogger("app.api.databases")


def _safe_backup_filename(filename: str) -> str:
    """Защита от path traversal: имя бэкапа не должно содержать разделителей путей."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла резервной копии.")
    return filename


def resolve_ip(ips: list) -> Optional[str]:
    from app.core.netutils import pick_external_ip
    return pick_external_ip(ips)

def get_vm_ip_by_name(vm_name: str) -> Optional[str]:
    try:
        from app.core.k8s_client import K8sClient
        client = K8sClient()
        vm_data = client.get_vm(vm_name)
        if vm_data and vm_data.get("ips"):
            return resolve_ip(vm_data["ips"])
    except Exception as e:
        logger.error(f"Failed to get VM IP for {vm_name}: {e}")
    return None

class DatabaseCreateRequest(BaseModel):
    name: str = Field(..., description="Имя базы данных (a-z, 0-9, _)")
    engine: str = Field("postgresql", description="СУБД (postgresql или mysql)")

class DatabaseResponse(BaseModel):
    id: int
    db_name: str
    engine: str
    db_user: str
    db_password: str
    status: str
    owner_username: str
    associated_vm_id: Optional[int] = None
    associated_vm_name: Optional[str] = None
    db_host: str

def generate_db_credentials(db_name: str):
    # Генерация случайного суффикса для логина
    suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    db_user = f"u_{suffix}"
    # Сложный пароль
    chars = string.ascii_letters + string.digits
    db_password = ''.join(secrets.choice(chars) for _ in range(16))
    return db_user, db_password

@router.post("", response_model=DatabaseResponse, status_code=status.HTTP_201_CREATED)
def create_database(req: DatabaseCreateRequest, current_user: User = Depends(get_current_user)):
    # Валидация имени БД
    if not re.match(r"^[a-z0-9_]{3,32}$", req.name):
        raise HTTPException(
            status_code=400, 
            detail="Имя БД должно быть длиной от 3 до 32 символов и содержать только строчные латинские буквы, цифры и знак подчеркивания."
        )
    
    if req.engine not in ["postgresql", "mysql"]:
        raise HTTPException(status_code=400, detail="Поддерживаются только postgresql и mysql.")

    from app.core.ratelimit import check_rate_limit
    check_rate_limit(current_user, "create_database")

    db = SessionLocal()
    try:
        # Проверка лимитов для студентов (квота: макс 3 базы данных)
        if current_user.role != "admin":
            db_count = db.query(UserDatabase).filter(UserDatabase.owner_id == current_user.id).count()
            if db_count >= 3:
                raise HTTPException(status_code=400, detail="Достигнут лимит на создание баз данных (макс. 3).")

        # Проверка уникальности имени в системе
        existing = db.query(UserDatabase).filter(UserDatabase.db_name == req.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="База данных с таким именем уже зарегистрирована в системе.")

        db_user, db_password = generate_db_credentials(req.name)

        # Приватная БД — это PVC на 5 ГБ (DB_PVC_SIZE_GB), на том же
        # STORAGE_CLASS, что и диски ВМ, бэкапы и сетевые диски. Раньше место
        # под неё не проверялось вообще — база создавалась, даже если
        # хранилищу (LVM-пулу или корневому диску хоста) уже нечего было ей
        # предложить.
        from app.core.k8s_client import DB_PVC_SIZE_GB
        from app.core.capacity import lock_host_capacity, ensure_storage_capacity
        lock_host_capacity(db)
        ensure_storage_capacity(db, extra_gb=DB_PVC_SIZE_GB)

        # Выделение ресурсов (под) СУБД в Kubernetes
        try:
            from app.core.k8s_client import K8sClient
            k8s = K8sClient()
            k8s.create_private_db(
                db_name=req.name,
                engine=req.engine,
                db_user=db_user,
                db_password=db_password,
                vm_name=None,
                namespace="default"
            )
        except Exception as e:
            logger.error(f"Failed to create private DB in K8s: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка при создании ресурсов БД в Kubernetes: {e}")

        # Сохранение записи в системной БД
        new_db = UserDatabase(
            db_name=req.name,
            db_type=req.engine,
            db_user=db_user,
            db_password=encrypt_secret(db_password),
            owner_id=current_user.id,
            status="Active"
        )
        db.add(new_db)
        db.commit()
        db.refresh(new_db)

        return DatabaseResponse(
            id=new_db.id,
            db_name=new_db.db_name,
            engine=new_db.db_type,
            db_user=new_db.db_user,
            db_password=db_password,
            status="Pending",  # Первоначальный статус запуска пода
            owner_username=current_user.username,
            associated_vm_id=None,
            associated_vm_name=None,
            db_host=f"db-service-{new_db.db_name}"
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("", response_model=List[DatabaseResponse])
def list_databases(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            databases = db.query(UserDatabase).all()
        else:
            databases = db.query(UserDatabase).filter(UserDatabase.owner_id == current_user.id).all()
            
        from app.core.k8s_client import K8sClient
        k8s = K8sClient()
        
        res = []
        for d in databases:
            owner = db.query(User).filter(User.id == d.owner_id).first()
            owner_name = owner.username if owner else "Unknown"
            
            vm_name = None
            if d.associated_vm_id:
                vm = db.query(VMTask).filter(VMTask.id == d.associated_vm_id).first()
                if vm:
                    vm_name = vm.name
            
            # Получаем динамический статус пода базы из K8s
            real_status = k8s.get_private_db_status(d.db_name)
            
            res.append(DatabaseResponse(
                id=d.id,
                db_name=d.db_name,
                engine=d.db_type,
                db_user=d.db_user,
                db_password=decrypt_secret(d.db_password),
                status=real_status,
                owner_username=owner_name,
                associated_vm_id=d.associated_vm_id,
                associated_vm_name=vm_name,
                db_host=f"db-service-{d.db_name}"
            ))
        return res
    finally:
        db.close()

@router.delete("/{db_id}", status_code=status.HTTP_200_OK)
def delete_database(db_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")

        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этой базы данных.")

        # Физическое удаление ресурсов в Kubernetes
        try:
            from app.core.k8s_client import K8sClient
            k8s = K8sClient()
            k8s.delete_private_db(user_db.db_name)
        except Exception as e:
            logger.error(f"Failed to delete Kubernetes resources for DB {user_db.db_name}: {e}")

        # Удаление из системной БД
        db.delete(user_db)
        db.commit()
        return {"status": "Database deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

class DatabaseBindRequest(BaseModel):
    vm_id: Optional[int] = None

@router.post("/{db_id}/bind", status_code=status.HTTP_200_OK)
def bind_database(db_id: int, req: DatabaseBindRequest, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")

        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")

        from app.core.k8s_client import K8sClient
        k8s = K8sClient()

        if req.vm_id is not None:
            vm = db.query(VMTask).filter(VMTask.id == req.vm_id).first()
            if not vm:
                raise HTTPException(status_code=404, detail="Виртуальная машина не найдена")
            if current_user.role != "admin" and vm.owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="Виртуальная машина вам не принадлежит")
            
            # Обновляем сетевую политику: разрешаем доступ только от выбранной ВМ
            try:
                k8s.update_db_network_policy(user_db.db_name, vm.name)
            except Exception as e:
                logger.error(f"Failed to bind network policy for DB {user_db.db_name} to VM {vm.name}: {e}")
                raise HTTPException(status_code=500, detail=f"Ошибка настройки сетевого доступа: {e}")

            user_db.associated_vm_id = req.vm_id
        else:
            # При отвязке блокируем весь входящий трафик к базе данных
            try:
                k8s.update_db_network_policy(user_db.db_name, None)
            except Exception as e:
                logger.error(f"Failed to clear network policy for DB {user_db.db_name}: {e}")
                raise HTTPException(status_code=500, detail=f"Ошибка настройки сетевого доступа: {e}")

            user_db.associated_vm_id = None

        db.commit()
        return {"status": "Database bound status updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

class SQLQueryRequest(BaseModel):
    sql: str

@router.get("/{db_id}/metrics")
def get_database_metrics(db_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.core.k8s_client import K8sClient
        k8s = K8sClient()
        db_password = decrypt_secret(user_db.db_password)
        
        try:
            metrics = k8s.get_db_metrics(
                db_name=user_db.db_name,
                engine=user_db.db_type,
                db_user=user_db.db_user,
                db_password=db_password
            )
            return metrics
        except Exception as e:
            logger.error(f"Failed to fetch DB metrics for {user_db.db_name}: {e}")
            return {
                "db_size_mb": 0.05,
                "cpu_load": 0.0,
                "memory_usage": 0.0,
                "active_sessions": 0,
                "error": str(e)
            }
    finally:
        db.close()

@router.post("/{db_id}/query")
def execute_sql_query(db_id: int, req: SQLQueryRequest, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        sql = req.sql.strip()
        from app.core.k8s_client import K8sClient
        k8s = K8sClient()
        db_password = decrypt_secret(user_db.db_password)
        
        try:
            raw_output = k8s.execute_db_query(
                db_name=user_db.db_name,
                engine=user_db.db_type,
                db_user=user_db.db_user,
                db_password=db_password,
                sql=sql
            )
            
            import csv
            from io import StringIO

            # Реальные ошибки SQL уже приходят исключением из execute_db_query
            # (ненулевой код клиента), поэтому строковую проверку убрали —
            # она давала ложные срабатывания на данных со словом "error".
            if user_db.db_type == "postgresql":
                lines = raw_output.strip().split('\n')
                if not lines or (len(lines) == 1 and not ',' in lines[0] and not '"' in lines[0]):
                    return {"columns": None, "rows": None, "message": raw_output.strip() or "Запрос выполнен успешно"}
                
                f = StringIO(raw_output.strip())
                reader = csv.reader(f)
                rows = list(reader)
                if not rows:
                    return {"columns": None, "rows": None, "message": "Запрос выполнен успешно"}
                columns = rows[0]
                data_rows = rows[1:]
                return {"columns": columns, "rows": data_rows, "message": None}
            else: # mysql / mariadb
                lines = [line.split('\t') for line in raw_output.strip().split('\n') if line]
                if not lines:
                    return {"columns": None, "rows": None, "message": "Запрос выполнен успешно"}
                if len(lines) == 1 and len(lines[0]) == 1 and not lines[0][0]:
                    return {"columns": None, "rows": None, "message": "Запрос выполнен успешно"}
                
                columns = lines[0]
                data_rows = lines[1:]
                if len(lines) == 1 and len(columns) == 1:
                    return {"columns": None, "rows": None, "message": columns[0]}
                
                return {"columns": columns, "rows": data_rows, "message": None}
                
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()

@router.get("/{db_id}/tables")
def get_database_tables(db_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.core.k8s_client import K8sClient
        k8s = K8sClient()
        db_password = decrypt_secret(user_db.db_password)
        
        if user_db.db_type == "postgresql":
            sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
        else:
            sql = "SHOW TABLES;"
            
        try:
            raw_output = k8s.execute_db_query(
                db_name=user_db.db_name,
                engine=user_db.db_type,
                db_user=user_db.db_user,
                db_password=db_password,
                sql=sql
            )
            
            tables = []
            lines = raw_output.strip().split('\n')
            if len(lines) >= 2:
                for line in lines[1:]:
                    val = line.replace('"', '').strip()
                    if val:
                        tables.append(val)
            return tables
        except Exception as e:
            logger.error(f"Failed to fetch tables for {user_db.db_name}: {e}")
            return []
    finally:
        db.close()

@router.get("/{db_id}/backups")
def list_database_backups(db_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.api.s3 import get_minio_client
        client = get_minio_client()
        bucket = "database-backups"
        
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                
            objects = client.list_objects(bucket, prefix=f"{user_db.db_name}/", recursive=True)
            res = []
            for obj in objects:
                filename = obj.object_name.split("/")[-1]
                res.append({
                    "filename": filename,
                    "size_bytes": obj.size,
                    "last_modified": obj.last_modified.strftime("%Y-%m-%d %H:%M:%S") if obj.last_modified else None
                })
            res.sort(key=lambda x: x["filename"], reverse=True)
            return res
        except Exception as e:
            logger.error(f"Failed to list backups for {user_db.db_name}: {e}")
            return []
    finally:
        db.close()

@router.post("/{db_id}/backups")
def create_database_backup(db_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.core.k8s_client import K8sClient
        k8s = K8sClient()
        db_password = decrypt_secret(user_db.db_password)
        
        try:
            dump_content = k8s.execute_db_backup(
                db_name=user_db.db_name,
                engine=user_db.db_type,
                db_user=user_db.db_user,
                db_password=db_password
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка генерации бэкапа: {e}")
            
        from io import BytesIO
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"backup_{user_db.db_name}_{timestamp}.sql"
        object_name = f"{user_db.db_name}/{_safe_backup_filename(filename)}"
        
        dump_bytes = dump_content.encode("utf-8")
        data_stream = BytesIO(dump_bytes)
        
        from app.api.s3 import get_minio_client
        client = get_minio_client()
        bucket = "database-backups"
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            
        client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=data_stream,
            length=len(dump_bytes),
            content_type="application/sql"
        )
        
        return {
            "status": "Success",
            "filename": filename,
            "size_bytes": len(dump_bytes)
        }
    finally:
        db.close()

@router.post("/{db_id}/backups/{filename}/restore")
def restore_database_backup(db_id: int, filename: str, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.api.s3 import get_minio_client
        client = get_minio_client()
        bucket = "database-backups"
        object_name = f"{user_db.db_name}/{_safe_backup_filename(filename)}"
        
        try:
            response = client.get_object(bucket, object_name)
            sql_content = response.read().decode("utf-8")
            response.close()
            response.release_conn()
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Резервная копия не найдена в хранилище: {e}")
            
        from app.core.k8s_client import K8sClient
        k8s = K8sClient()
        db_password = decrypt_secret(user_db.db_password)
        
        try:
            restore_output = k8s.execute_db_restore(
                db_name=user_db.db_name,
                engine=user_db.db_type,
                db_user=user_db.db_user,
                db_password=db_password,
                sql_content=sql_content
            )
            return {"status": "Success", "detail": restore_output}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка восстановления базы данных: {e}")
    finally:
        db.close()

@router.delete("/{db_id}/backups/{filename}")
def delete_database_backup(db_id: int, filename: str, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.api.s3 import get_minio_client
        client = get_minio_client()
        bucket = "database-backups"
        object_name = f"{user_db.db_name}/{_safe_backup_filename(filename)}"
        
        try:
            client.remove_object(bucket, object_name)
            return {"status": "Success", "detail": "Резервная копия удалена"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка удаления резервной копии: {e}")
    finally:
        db.close()

@router.get("/{db_id}/backups/{filename}/download")
def download_database_backup(db_id: int, filename: str, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user_db = db.query(UserDatabase).filter(UserDatabase.id == db_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="База данных не найдена")
            
        if current_user.role != "admin" and user_db.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
            
        from app.api.s3 import get_minio_client
        client = get_minio_client()
        bucket = "database-backups"
        object_name = f"{user_db.db_name}/{_safe_backup_filename(filename)}"
        
        try:
            response = client.get_object(bucket, object_name)
            from fastapi.responses import StreamingResponse
            return StreamingResponse(
                response,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Резервная копия не найдена: {e}")
    finally:
        db.close()
