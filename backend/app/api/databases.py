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
from typing import List
from app.db import SessionLocal
from app.models.models import User, UserDatabase
from app.core.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("app.api.databases")

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
                    # Создаем юзера
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
            owner_username=current_user.username
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
            res.append(DatabaseResponse(
                id=d.id,
                db_name=d.db_name,
                engine=d.db_type,
                db_user=d.db_user,
                db_password=d.db_password,
                status=d.status,
                owner_username=owner_name
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
                    cursor.execute(f"DROP DATABASE IF EXISTS `{user_db.db_name}`;")
                    cursor.execute(f"DROP USER IF EXISTS '{user_db.db_user}'@'%';")
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
