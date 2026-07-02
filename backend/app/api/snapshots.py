import re
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List
from app.models.models import User
from app.core.auth import get_current_user
from app.core.k8s_client import K8sClient
from app.api.vms import check_vm_ownership

router = APIRouter()
logger = logging.getLogger("app.api.snapshots")

def get_k8s_client():
    return K8sClient()

class SnapshotCreateRequest(BaseModel):
    name: str = Field(..., description="Имя снимка (a-z, 0-9, -)")

class SnapshotResponse(BaseModel):
    name: str
    creation_time: str
    phase: str
    ready_to_use: bool

@router.get("/{vm_name}", response_model=List[SnapshotResponse])
def list_snapshots(vm_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        snaps = client.list_vm_snapshots(vm_name)
        res = []
        for s in snaps:
            # Превращаем время в читаемый формат
            time_str = s["creation_time"] or "Unknown"
            if time_str and time_str != "Unknown":
                # Формат UTC ISO
                time_str = time_str.replace("T", " ").replace("Z", "")
            res.append(SnapshotResponse(
                name=s["name"],
                creation_time=time_str,
                phase=s["phase"],
                ready_to_use=s["ready_to_use"]
            ))
        return res
    except Exception as e:
        logger.error(f"Error listing snapshots for VM {vm_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_name}", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED)
def create_snapshot(vm_name: str, req: SnapshotCreateRequest, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    
    if not re.match(r"^[a-z0-9-]{3,32}$", req.name):
        raise HTTPException(
            status_code=400,
            detail="Имя снимка должно содержать только строчные латинские буквы, цифры и дефис."
        )

    # Имя снапшота в Kubernetes
    full_snapshot_name = f"snap-{vm_name}-{req.name}"

    try:
        client.create_vm_snapshot(vm_name, full_snapshot_name)
        return SnapshotResponse(
            name=full_snapshot_name,
            creation_time="Только что создается",
            phase="Pending",
            ready_to_use=False
        )
    except Exception as e:
        logger.error(f"Error creating snapshot for VM {vm_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания снимка в Kubernetes: {e}")

@router.delete("/{vm_name}/{snapshot_name}")
def delete_snapshot(vm_name: str, snapshot_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    try:
        client.delete_vm_snapshot(snapshot_name)
        return {"status": "Snapshot deletion request sent"}
    except Exception as e:
        logger.error(f"Error deleting snapshot {snapshot_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{vm_name}/{snapshot_name}/restore")
def restore_snapshot(vm_name: str, snapshot_name: str, client: K8sClient = Depends(get_k8s_client), current_user: User = Depends(get_current_user)):
    check_vm_ownership(vm_name, current_user)
    
    # Перед восстановлением проверим, выключена ли виртуальная машина
    try:
        vm = client.get_vm(vm_name)
        if vm.get("status") == "Running":
            raise HTTPException(
                status_code=400,
                detail="Виртуальная машина должна быть остановлена перед восстановлением из снимка."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Could not verify VM status: {e}")

    try:
        client.restore_vm_snapshot(vm_name, snapshot_name)
        return {"status": "VM restore request sent successfully"}
    except Exception as e:
        logger.error(f"Error restoring snapshot {snapshot_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка восстановления снимка в Kubernetes: {e}")
