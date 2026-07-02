from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.models.models import User, VMTask, Cluster, UserDatabase, UserBucket, UserVolume, UserMailbox
from app.core.auth import hash_password, verify_password, create_access_token, get_current_user, check_admin, get_db

router = APIRouter()

# --- СХЕМЫ PYDANTIC ---

class LoginRequest(BaseModel):
    username: str = Field(..., description="Имя пользователя")
    password: str = Field(..., description="Пароль")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str

class UserCreateRequest(BaseModel):
    username: str = Field(..., description="Имя пользователя")
    password: str = Field(..., description="Пароль")
    role: str = Field("student", description="Роль (admin/student)")
    max_vcpus: int = Field(4, description="Лимит CPU ядер")
    max_ram_mb: int = Field(4096, description="Лимит RAM в МБ")
    max_vms: int = Field(2, description="Лимит количества ВМ")
    max_storage_gb: int = Field(40, description="Лимит дискового пространства в ГБ")

class UserQuotaResponse(BaseModel):
    username: str
    role: str
    balance: float
    quotas: dict
    usage: dict

class UserListItem(BaseModel):
    id: int
    username: str
    role: str
    balance: float
    max_vcpus: int
    max_ram_mb: int
    max_vms: int
    max_storage_gb: int

class UserUpdateRequest(BaseModel):
    max_vcpus: int
    max_ram_mb: int
    max_vms: int
    max_storage_gb: int
    password: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

# --- ЭНДПОИНТЫ ---

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Аутентификация пользователя и выдача сессионного токена"""
    res = await db.execute(select(User).filter_by(username=req.username))
    user = res.scalars().first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    token = create_access_token({"sub": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username
    }

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: UserCreateRequest, admin: User = Depends(check_admin), db: AsyncSession = Depends(get_db)):
    """Регистрация нового пользователя (только для преподавателя/администратора)"""
    res = await db.execute(select(User).filter_by(username=req.username))
    if res.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким именем уже существует"
        )
    
    new_user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
        max_vcpus=req.max_vcpus,
        max_ram_mb=req.max_ram_mb,
        max_vms=req.max_vms,
        max_storage_gb=req.max_storage_gb
    )
    db.add(new_user)
    await db.commit()
    return {"status": "created", "username": req.username}

@router.get("/me", response_model=UserQuotaResponse)
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Информация о текущем пользователе, его лимитах и текущем потреблении ресурсов"""
    # Считаем текущее потребление ресурсов пользователя
    vms_res = await db.execute(select(VMTask).filter_by(owner_id=user.id))
    vms = vms_res.scalars().all()
    
    used_vcpus = sum(vm.cpu_cores for vm in vms)
    used_ram = sum(vm.memory_gb * 1024 for vm in vms) # memory_gb to MB
    used_vms = len(vms)
    
    # Считаем занятое дисковое пространство (диски ВМ + сетевые диски)
    used_storage = sum(vm.disk_gb for vm in vms)
    
    vol_res = await db.execute(select(UserVolume).filter_by(owner_id=user.id))
    volumes = vol_res.scalars().all()
    used_storage += sum(vol.size_gb for vol in volumes)

    return {
        "username": user.username,
        "role": user.role,
        "balance": user.balance,
        "quotas": {
            "max_vcpus": user.max_vcpus,
            "max_ram_mb": user.max_ram_mb,
            "max_vms": user.max_vms,
            "max_storage_gb": user.max_storage_gb
        },
        "usage": {
            "vcpus": used_vcpus,
            "ram_mb": used_ram,
            "vms": used_vms,
            "storage_gb": used_storage
        }
    }

@router.get("/users", response_model=List[UserListItem])
async def list_users(admin: User = Depends(check_admin), db: AsyncSession = Depends(get_db)):
    """Список всех пользователей (только для преподавателя/администратора)"""
    res = await db.execute(select(User).order_by(User.id.desc()))
    users = res.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "balance": u.balance,
            "max_vcpus": u.max_vcpus,
            "max_ram_mb": u.max_ram_mb,
            "max_vms": u.max_vms,
            "max_storage_gb": u.max_storage_gb
        } for u in users if u.username != "admin" # Скрываем системного admin
    ]

@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: User = Depends(check_admin), db: AsyncSession = Depends(get_db)):
    """Удаление пользователя и всех его ресурсов (только для администратора)"""
    res = await db.execute(select(User).filter_by(id=user_id))
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Нельзя удалить системного администратора")

    # 1. Удаляем связанные ресурсы ВМ и кластеры (логически)
    # На практике реальные K8s ресурсы должны быть удалены. Мы каскадно удаляем их записи в БД.
    await db.execute(select(VMTask).filter_by(owner_id=user.id))
    # Для простоты удаляем пользователя из БД
    await db.delete(user)
    await db.commit()
    return {"status": "deleted"}

@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UserUpdateRequest, admin: User = Depends(check_admin), db: AsyncSession = Depends(get_db)):
    """Редактирование лимитов и пароля пользователя администратором"""
    res = await db.execute(select(User).filter_by(id=user_id))
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.max_vcpus = req.max_vcpus
    user.max_ram_mb = req.max_ram_mb
    user.max_vms = req.max_vms
    user.max_storage_gb = req.max_storage_gb
    
    if req.password and req.password.strip():
        user.password_hash = hash_password(req.password.strip())
        
    await db.commit()
    return {"status": "updated"}

@router.post("/change-password")
async def change_own_password(req: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Смена пароля самим пользователем"""
    if not verify_password(req.password_hash if hasattr(req, "password_hash") else req.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный старый пароль")
    
    current_user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"status": "success", "detail": "Пароль успешно изменен"}
