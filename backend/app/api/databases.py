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
