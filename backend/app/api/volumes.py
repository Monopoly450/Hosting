import re
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.db import SessionLocal
from app.models.models import User, UserVolume, VMTask
from app.core.auth import get_current_user
from app.core.k8s_client import K8sClient

router = APIRouter()
logger = logging.getLogger("app.api.volumes")

def get_k8s_client():
    return K8sClient()

class VolumeCreateRequest(BaseModel):
    name: str = Field(..., description="Имя сетевого диска (a-z, 0-9, -)")
    size_gb: int = Field(..., description="Размер диска в ГБ", ge=1, le=500)

class VolumeResponse(BaseModel):
    id: int
    name: str
    size_gb: int
    attached_vm_name: Optional[str] = None
    status: str
    owner_username: str
    created_at: str

@router.post("", response_model=VolumeResponse, status_code=status.HTTP_201_CREATED)
def create_volume(req: VolumeCreateRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    if not re.match(r"^[a-z0-9-]{3,32}$", req.name):
        raise HTTPException(
            status_code=400,
            detail="Имя диска должно содержать только строчные латинские буквы, цифры и дефис."
        )

    db = SessionLocal()
    try:
        # Проверяем квоту накопителя (max_storage_gb)
        if current_user.role != "admin":
            owned_vms = db.query(VMTask).filter(VMTask.owner_id == current_user.id).all()
            owned_vols = db.query(UserVolume).filter(UserVolume.owner_id == current_user.id).all()
            total_storage = sum(vm.disk_gb for vm in owned_vms) + sum(vol.size_gb for vol in owned_vols)
            
            if total_storage + req.size_gb > current_user.max_storage_gb:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно квоты диска. Свободно: {current_user.max_storage_gb - total_storage} ГБ, запрашивается: {req.size_gb} ГБ."
                )

        full_pvc_name = f"vol-{current_user.id}-{req.name}"

        # Проверяем уникальность имени диска в БД
        existing = db.query(UserVolume).filter(UserVolume.name == full_pvc_name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Сетевой диск с таким именем уже существует.")

        # Создаем PVC в Kubernetes
        try:
            client.create_pvc(full_pvc_name, req.size_gb)
        except Exception as e:
            logger.error(f"Failed to create PVC in Kubernetes: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка создания PVC в кластере: {e}")

        # Сохраняем в БД
        new_vol = UserVolume(
            name=full_pvc_name,
            size_gb=req.size_gb,
            owner_id=current_user.id,
            status="Available"
        )
        db.add(new_vol)
        db.commit()
        db.refresh(new_vol)

        return VolumeResponse(
            id=new_vol.id,
            name=req.name,
            size_gb=new_vol.size_gb,
            status=new_vol.status,
            owner_username=current_user.username,
            created_at=new_vol.created_at.strftime("%Y-%m-%d %H:%M:%S")
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("", response_model=List[VolumeResponse])
def list_volumes(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        if current_user.role == "admin":
            volumes = db.query(UserVolume).all()
        else:
            volumes = db.query(UserVolume).filter(UserVolume.owner_id == current_user.id).all()

        res = []
        for v in volumes:
            owner = db.query(User).filter(User.id == v.owner_id).first()
            owner_name = owner.username if owner else "Unknown"
            
            attached_vm_name = None
            if v.attached_vm_id:
                vm = db.query(VMTask).filter(VMTask.id == v.attached_vm_id).first()
                if vm:
                    attached_vm_name = vm.name

            # Убираем префикс vol-ID- из отображаемого имени
            display_name = re.sub(r"^vol-\d+-", "", v.name)

            res.append(VolumeResponse(
                id=v.id,
                name=display_name,
                size_gb=v.size_gb,
                attached_vm_name=attached_vm_name,
                status=v.status,
                owner_username=owner_name,
                created_at=v.created_at.strftime("%Y-%m-%d %H:%M:%S")
            ))
        return res
    finally:
        db.close()

@router.post("/{vol_id}/attach/{vm_name}")
def attach_volume(vol_id: int, vm_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        vol = db.query(UserVolume).filter(UserVolume.id == vol_id).first()
        if not vol:
            raise HTTPException(status_code=404, detail="Сетевой диск не найден")

        if current_user.role != "admin" and vol.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого диска.")

        if vol.status == "Attached":
            raise HTTPException(status_code=400, detail="Диск уже подключен к виртуальной машине.")

        # Находим виртуальную машину
        vm = db.query(VMTask).filter(VMTask.name == vm_name).first()
        if not vm:
            raise HTTPException(status_code=404, detail="Виртуальная машина не найдена")

        if current_user.role != "admin" and vm.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этой виртуальной машины.")

        # Горячее подключение в KubeVirt
        try:
            # Имя тома внутри ВМ (убираем спецсимволы)
            clean_vol_name = re.sub(r"[^a-zA-Z0-9-]", "", re.sub(r"^vol-\d+-", "", vol.name))
            client.add_vm_volume(vm.name, vol.name, volume_name=clean_vol_name)
        except Exception as e:
            logger.error(f"Failed to hotplug volume {vol.name} to VM {vm.name}: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка горячего подключения в Kubernetes: {e}")

        # Обновляем БД
        vol.attached_vm_id = vm.id
        vol.status = "Attached"
        db.commit()

        return {"status": "Volume attached successfully", "vm": vm_name}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.post("/{vol_id}/detach")
def detach_volume(vol_id: int, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        vol = db.query(UserVolume).filter(UserVolume.id == vol_id).first()
        if not vol:
            raise HTTPException(status_code=404, detail="Сетевой диск не найден")

        if current_user.role != "admin" and vol.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого диска.")

        if vol.status != "Attached" or not vol.attached_vm_id:
            raise HTTPException(status_code=400, detail="Диск не подключен к виртуальной машине.")

        # Находим виртуальную машину
        vm = db.query(VMTask).filter(VMTask.id == vol.attached_vm_id).first()
        if not vm:
            raise HTTPException(status_code=404, detail="Связанная ВМ не найдена в системе.")

        # Горячее отключение в KubeVirt
        try:
            clean_vol_name = re.sub(r"[^a-zA-Z0-9-]", "", re.sub(r"^vol-\d+-", "", vol.name))
            client.remove_vm_volume(vm.name, volume_name=clean_vol_name)
        except Exception as e:
            logger.error(f"Failed to hot-unplug volume {vol.name} from VM {vm.name}: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка горячего отключения в Kubernetes: {e}")

        # Обновляем БД
        vol.attached_vm_id = None
        vol.status = "Available"
        db.commit()

        return {"status": "Volume detached successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.delete("/{vol_id}", status_code=status.HTTP_200_OK)
def delete_volume(vol_id: int, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        vol = db.query(UserVolume).filter(UserVolume.id == vol_id).first()
        if not vol:
            raise HTTPException(status_code=404, detail="Сетевой диск не найден")

        if current_user.role != "admin" and vol.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого диска.")

        # Если диск подключен к ВМ, сначала делаем горячее отключение
        if vol.status == "Attached" and vol.attached_vm_id:
            try:
                vm = db.query(VMTask).filter(VMTask.id == vol.attached_vm_id).first()
                if vm:
                    clean_vol_name = re.sub(r"[^a-zA-Z0-9-]", "", re.sub(r"^vol-\d+-", "", vol.name))
                    client.remove_vm_volume(vm.name, volume_name=clean_vol_name)
            except Exception as detach_err:
                logger.warning(f"Auto-detaching volume failed: {detach_err}")

        # Удаляем PVC из Kubernetes
        try:
            client.delete_pvc(vol.name)
        except Exception as e:
            logger.error(f"Failed to delete PVC in Kubernetes: {e}")

        # Удаляем из БД
        db.delete(vol)
        db.commit()
        return {"status": "Volume deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
