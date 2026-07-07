from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import select
from app.db import SessionLocal
from app.models.models import Cluster, VMTask, User
from app.queue_client import publish_task
from app.api.vms import VMCreationRequest
from app.core.auth import get_current_user

router = APIRouter()

class ClusterCreateRequest(BaseModel):
    name: str = Field(..., description="Имя кластера")
    vms: List[VMCreationRequest] = Field(..., description="Список виртуалок для создания внутри кластера")

class AttachVMRequest(BaseModel):
    vm_names: List[str] = Field(..., description="Список имен существующих ВМ для добавления в кластер")

@router.post("", status_code=status.HTTP_201_CREATED)
def create_cluster(req: ClusterCreateRequest, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        # Проверка существования кластера
        existing_cluster = db.query(Cluster).filter(Cluster.name == req.name).first()
        if existing_cluster:
            raise HTTPException(status_code=400, detail="Кластер с таким именем уже существует.")
            
        # Проверяем лимиты квот для обычных пользователей (студентов)
        if current_user.role != "admin":
            owned_vms = db.query(VMTask).filter(VMTask.owner_id == current_user.id).all()
            total_vms = len(owned_vms)
            total_cpus = sum(vm.cpu_cores for vm in owned_vms)
            total_ram = sum(vm.memory_gb * 1024 for vm in owned_vms)
            total_storage = sum(vm.disk_gb for vm in owned_vms)
            
            req_vms = len(req.vms)
            req_cpus = sum(vm.cpu_cores for vm in req.vms)
            req_ram = sum(vm.memory_gb * 1024 for vm in req.vms)
            req_storage = sum(vm.disk_gb for vm in req.vms)
            
            if total_vms + req_vms > current_user.max_vms:
                raise HTTPException(status_code=400, detail=f"Создание кластера превысит лимит ВМ (Лимит: {current_user.max_vms}, будет занято: {total_vms + req_vms}).")
            if total_cpus + req_cpus > current_user.max_vcpus:
                raise HTTPException(status_code=400, detail=f"Создание кластера превысит лимит CPU (Лимит: {current_user.max_vcpus}, будет занято: {total_cpus + req_cpus}).")
            if total_ram + req_ram > current_user.max_ram_mb:
                raise HTTPException(status_code=400, detail=f"Создание кластера превысит лимит RAM (Лимит: {current_user.max_ram_mb} МБ, будет занято: {total_ram + req_ram} МБ).")
            if total_storage + req_storage > current_user.max_storage_gb:
                raise HTTPException(status_code=400, detail=f"Создание кластера превысит лимит диска (Лимит: {current_user.max_storage_gb} ГБ, будет занято: {total_storage + req_storage} ГБ).")

        cluster = Cluster(name=req.name, network_name=f"{req.name}-net", owner_id=current_user.id)
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        
        # Добавляем задачи для каждой ВМ:
        for vm_req in req.vms:
            # Проверка имени ВМ
            if db.query(VMTask).filter(VMTask.name == vm_req.name).first():
                continue
                
            task = VMTask(
                name=vm_req.name,
                cluster_id=cluster.id,
                owner_id=current_user.id,
                os_type=vm_req.os_type,
                cpu_cores=vm_req.cpu_cores,
                memory_gb=vm_req.memory_gb,
                disk_gb=vm_req.disk_gb,
                custom_image=vm_req.custom_image,
                packages=vm_req.packages,
                network_drives=vm_req.network_drives,
                cloud_init_template=vm_req.cloud_init_template,
                custom_user_data=vm_req.custom_user_data,
                iso_url=vm_req.iso_url,
                ssh_key=vm_req.ssh_key,
                status="Pending"
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            
            publish_task("vm_tasks", {
                "task_id": task.id,
                "action": "create_vm"
            })
            
        return {"status": "creating", "cluster_id": cluster.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.post("/{cluster_id}/attach")
def attach_vms_to_cluster(cluster_id: int, req: AttachVMRequest, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Кластер не найден")
            
        if current_user.role != "admin" and cluster.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого кластера.")
            
        # Для существующих ВМ нам нужно обновить манифест в k8s, добавив multus интерфейс.
        for vm_name in req.vm_names:
            task = db.query(VMTask).filter(VMTask.name == vm_name).first()
            if not task:
                # Если ВМ была создана до внедрения БД, создадим для нее запись
                task = VMTask(name=vm_name, status="Running", cluster_id=cluster.id, owner_id=current_user.id)
                db.add(task)
                db.commit()
                db.refresh(task)
            else:
                if current_user.role != "admin" and task.owner_id != current_user.id:
                    continue  # Пропускаем чужие ВМ
                task.cluster_id = cluster.id
                db.commit()
                
            publish_task("vm_tasks", {
                "task_id": task.id,
                "action": "attach_network",
                "network_name": cluster.network_name
            })
            
        return {"status": "attaching"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("")
def list_clusters(current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        from app.core.k8s_client import K8sClient
        client = K8sClient()
        try:
            k8s_vms = client.list_vms()
            k8s_status_map = {vm["name"]: vm["status"] for vm in k8s_vms}
        except Exception:
            k8s_status_map = {}

        if current_user.role == "admin":
            clusters = db.query(Cluster).all()
        else:
            clusters = db.query(Cluster).filter(Cluster.owner_id == current_user.id).all()
            
        result = []
        for c in clusters:
            vms_data = []
            for v in c.vms:
                real_status = k8s_status_map.get(v.name, v.status or "Stopped")
                vms_data.append({
                    "name": v.name,
                    "status": real_status,
                    "os_type": v.os_type,
                    "cpu_cores": v.cpu_cores,
                    "memory_gb": v.memory_gb,
                    "disk_gb": v.disk_gb
                })
            
            # Determine overall cluster status based on VMs
            if not vms_data:
                cluster_status = "Active"
            else:
                norms = [vm["status"].lower() for vm in vms_data]
                if any(s in ["pending", "provisioning", "starting", "importing"] for s in norms):
                    cluster_status = "Creating"
                elif any(s in ["stopping"] for s in norms):
                    cluster_status = "Updating"
                elif any(s == "error" for s in norms):
                    cluster_status = "Error"
                elif all(s == "stopped" for s in norms):
                    cluster_status = "Stopped"
                else:
                    cluster_status = "Active"
            
            result.append({
                "id": c.id,
                "name": c.name,
                "network_name": c.network_name,
                "status": cluster_status,
                "created_at": c.created_at,
                "vms": vms_data
            })
            
        return result
    finally:
        db.close()

@router.delete("/{cluster_id}", status_code=status.HTTP_200_OK)
def delete_cluster(cluster_id: int, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Кластер не найден")
            
        if current_user.role != "admin" and cluster.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен: Вы не являетесь владельцем этого кластера.")
        
        # Получаем все ВМ в кластере
        vms = db.query(VMTask).filter(VMTask.cluster_id == cluster_id).all()
        for vm in vms:
            # Отправляем задачу на удаление каждой ВМ
            publish_task("vm_tasks", {
                "task_id": vm.id,
                "action": "delete_vm"
            })
            db.delete(vm)
            
        # Удаляем сетевое окружение кластера через воркер
        publish_task("vm_tasks", {
            "task_id": cluster.id,
            "action": "delete_cluster_env"
        })
        
        db.delete(cluster)
        db.commit()
        return {"status": "Deleting cluster and its VMs"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
