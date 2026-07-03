import os
import re
import string
import secrets
import logging
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import pymysql
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.db import SessionLocal
from app.models.models import User, UserDatabase, VMTask
from app.core.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("app.api.databases")

def resolve_ip(ips: list) -> Optional[str]:
    for ip in ips:
        if (
            not ip.startswith("10.244.") and 
            not ip.startswith("10.42.") and 
            not ip.startswith("10.0.2.") and 
            not ip.startswith("127.0.") and 
            ":" not in ip
        ):
            return ip
    for ip in ips:
        if (ip.startswith("10.42.") or ip.startswith("10.244.")) and ":" not in ip:
            return ip
    for ip in ips:
        if ":" not in ip:
            return ip
    return ips[0] if ips else None

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

def update_mysql_user_host(db_user: str, new_host: str):
    try:
        conn = pymysql.connect(
            host="127.0.0.1",
            user="root",
            password=os.getenv("MARIADB_ROOT_PASSWORD", "mariadb-root-secret-2026"),
            port=3306
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT Host FROM mysql.user WHERE User = %s;", (db_user,))
            row = cursor.fetchone()
            if row:
                old_host = row[0]
                if old_host != new_host:
                    cursor.execute(f"RENAME USER '{db_user}'@'{old_host}' TO '{db_user}'@'{new_host}';")
                    cursor.execute("FLUSH PRIVILEGES;")
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update MariaDB user host for {db_user} to {new_host}: {e}")
        raise e

def update_postgres_role_login(db_user: str, allow_login: bool):
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user="postgres",
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            host="127.0.0.1",
            port=5432
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cursor:
            login_clause = "LOGIN" if allow_login else "NOLOGIN"
            cursor.execute(f'ALTER ROLE "{db_user}" {login_clause};')
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update Postgres role login for {db_user}: {e}")
        raise e

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

        if req.engine == "postgresql":
            # Физическое создание в PostgreSQL
            try:
                conn = psycopg2.connect(
                    dbname="postgres",
                    user="postgres",
                    password=os.getenv("POSTGRES_PASSWORD", "postgres"),
                    host="127.0.0.1",
                    port=5432
                )
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                with conn.cursor() as cursor:
                    # Создаем БД
                    cursor.execute(f'CREATE DATABASE "{req.name}";')
                    # Создаем юзера с возможностью входа (LOGIN по умолчанию)
                    cursor.execute(f'CREATE USER "{db_user}" WITH PASSWORD \'{db_password}\';')
                    # Даем права
                    cursor.execute(f'GRANT ALL PRIVILEGES ON DATABASE "{req.name}" TO "{db_user}";')
                conn.close()
            except Exception as e:
                logger.error(f"Postgres DB creation failed: {e}")
                raise HTTPException(status_code=500, detail=f"Ошибка при создании базы в PostgreSQL: {e}")

        elif req.engine == "mysql":
            # Физическое создание в MariaDB/MySQL
            try:
                conn = pymysql.connect(
                    host="127.0.0.1",
                    user="root",
                    password=os.getenv("MARIADB_ROOT_PASSWORD", "mariadb-root-secret-2026"),
                    port=3306
                )
                with conn.cursor() as cursor:
                    cursor.execute(f"CREATE DATABASE `{req.name}`;")
                    cursor.execute(f"CREATE USER '{db_user}'@'%' IDENTIFIED BY '{db_password}';")
                    cursor.execute(f"GRANT ALL PRIVILEGES ON `{req.name}`.* TO '{db_user}'@'%';")
                    cursor.execute("FLUSH PRIVILEGES;")
                conn.close()
            except Exception as e:
                logger.error(f"MySQL DB creation failed: {e}")
                raise HTTPException(status_code=500, detail=f"Ошибка при создании базы в MariaDB: {e}")

        # Сохранение записи в системной БД
        new_db = UserDatabase(
            db_name=req.name,
            db_type=req.engine,
            db_user=db_user,
            db_password=db_password,
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
            db_password=new_db.db_password,
            status=new_db.status,
            owner_username=current_user.username,
            associated_vm_id=None,
            associated_vm_name=None
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
            
        res = []
        for d in databases:
            owner = db.query(User).filter(User.id == d.owner_id).first()
            owner_name = owner.username if owner else "Unknown"
            
            vm_name = None
            if d.associated_vm_id:
                vm = db.query(VMTask).filter(VMTask.id == d.associated_vm_id).first()
                if vm:
                    vm_name = vm.name
                    
            res.append(DatabaseResponse(
                id=d.id,
                db_name=d.db_name,
                engine=d.db_type,
                db_user=d.db_user,
                db_password=d.db_password,
                status=d.status,
                owner_username=owner_name,
                associated_vm_id=d.associated_vm_id,
                associated_vm_name=vm_name
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

        # Физическое удаление
        if user_db.db_type == "postgresql":
            try:
                conn = psycopg2.connect(
                    dbname="postgres",
                    user="postgres",
                    password=os.getenv("POSTGRES_PASSWORD", "postgres"),
                    host="127.0.0.1",
                    port=5432
                )
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                with conn.cursor() as cursor:
                    cursor.execute(f'DROP DATABASE IF EXISTS "{user_db.db_name}";')
                    cursor.execute(f'DROP USER IF EXISTS "{user_db.db_user}";')
                conn.close()
            except Exception as e:
                logger.error(f"Failed to drop Postgres DB: {e}")
                # Продолжаем удаление записи из БД в случае сбоя коннекта
        
        elif user_db.db_type == "mysql":
            try:
                conn = pymysql.connect(
                    host="127.0.0.1",
                    user="root",
                    password=os.getenv("MARIADB_ROOT_PASSWORD", "mariadb-root-secret-2026"),
                    port=3306
                )
                with conn.cursor() as cursor:
                    # Находим хост пользователя в СУБД перед удалением
                    cursor.execute("SELECT Host FROM mysql.user WHERE User = %s;", (user_db.db_user,))
                    row = cursor.fetchone()
                    if row:
                        user_host = row[0]
                        cursor.execute(f"DROP USER IF EXISTS '{user_db.db_user}'@'{user_host}';")
                    else:
                        cursor.execute(f"DROP USER IF EXISTS '{user_db.db_user}'@'%';")
                    cursor.execute(f"DROP DATABASE IF EXISTS `{user_db.db_name}`;")
                    cursor.execute("FLUSH PRIVILEGES;")
                conn.close()
            except Exception as e:
                logger.error(f"Failed to drop MySQL DB: {e}")

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

        if req.vm_id is not None:
            vm = db.query(VMTask).filter(VMTask.id == req.vm_id).first()
            if not vm:
                raise HTTPException(status_code=404, detail="Виртуальная машина не найдена")
            if current_user.role != "admin" and vm.owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="Виртуальная машина вам не принадлежит")
            
            # Получаем IP-адрес ВМ для настройки ограничений доступа
            vm_ip = get_vm_ip_by_name(vm.name)
            if not vm_ip:
                raise HTTPException(
                    status_code=400, 
                    detail="Не удалось получить IP-адрес виртуальной машины. Пожалуйста, запустите её перед выполнением привязки."
                )

            # Настраиваем доступ в СУБД
            if user_db.db_type == "postgresql":
                update_postgres_role_login(user_db.db_user, True)
            elif user_db.db_type == "mysql":
                update_mysql_user_host(user_db.db_user, vm_ip)

            user_db.associated_vm_id = req.vm_id
        else:
            # При отвязке блокируем внешний доступ к базе данных
            if user_db.db_type == "postgresql":
                update_postgres_role_login(user_db.db_user, False)
            elif user_db.db_type == "mysql":
                update_mysql_user_host(user_db.db_user, "127.0.0.1")

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
