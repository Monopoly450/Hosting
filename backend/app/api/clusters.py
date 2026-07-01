from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional
from app.db import SessionLocal
from app.models.models import Cluster, VMTask
from app.queue_client import publish_task
from app.api.vms import VMCreationRequest

router = APIRouter()

class ClusterCreateRequest(BaseModel):
    name: str = Field(..., description="Имя кластера")
    vms: List[VMCreationRequest] = Field(..., description="Список виртуалок для создания внутри кластера")

class AttachVMRequest(BaseModel):
    vm_names: List[str] = Field(..., description="Список имен существующих ВМ для добавления в кластер")

@router.post("", status_code=status.HTTP_201_CREATED)
def create_cluster(req: ClusterCreateRequest):
    db = SessionLocal()
    try:
        # Проверка существования кластера
        existing_cluster = db.query(Cluster).filter(Cluster.name == req.name).first()
        if existing_cluster:
            raise HTTPException(status_code=400, detail="Кластер с таким именем уже существует.")
            
        cluster = Cluster(name=req.name, network_name=f"{req.name}-net")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        
        # Отправляем задачи на создание сетевого свитча кластера (Multus) можно сделать через воркер,
        # но для начала воркер будет проверять наличие сети. 
        # Добавляем задачи для каждой ВМ:
        for vm_req in req.vms:
            # Проверка имени ВМ
            if db.query(VMTask).filter(VMTask.name == vm_req.name).first():
                continue # Пропускаем, или можно выбросить ошибку
                
            task = VMTask(
                name=vm_req.name,
                cluster_id=cluster.id,
                os_type=vm_req.os_type,
                cpu_cores=vm_req.cpu_cores,
                memory_gb=vm_req.memory_gb,
                disk_gb=vm_req.disk_gb,
                custom_image=vm_req.custom_image,
                packages=vm_req.packages,
                network_drives=vm_req.network_drives,
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.post("/{cluster_id}/attach")
def attach_vms_to_cluster(cluster_id: int, req: AttachVMRequest):
    db = SessionLocal()
    try:
        cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Кластер не найден")
            
        # Для существующих ВМ нам нужно обновить манифест в k8s, добавив multus интерфейс.
        # Это мы делегируем воркеру.
        for vm_name in req.vm_names:
            task = db.query(VMTask).filter(VMTask.name == vm_name).first()
            if not task:
                # Если ВМ была создана до внедрения БД, создадим для нее запись
                task = VMTask(name=vm_name, status="Running", cluster_id=cluster.id)
                db.add(task)
                db.commit()
                db.refresh(task)
            else:
                task.cluster_id = cluster.id
                db.commit()
                
            publish_task("vm_tasks", {
                "task_id": task.id,
                "action": "attach_network",
                "network_name": cluster.network_name
            })
            
        return {"status": "attaching"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.get("")
def list_clusters():
    db = SessionLocal()
    try:
        clusters = db.query(Cluster).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "network_name": c.network_name,
                "status": c.status,
                "created_at": c.created_at,
                "vms": [{
                    "name": v.name,
                    "status": v.status,
                    "os_type": v.os_type,
                    "cpu_cores": v.cpu_cores,
                    "memory_gb": v.memory_gb,
                    "disk_gb": v.disk_gb
                } for v in c.vms]
            } for c in clusters
        ]
    finally:
        db.close()

@router.delete("/{cluster_id}", status_code=status.HTTP_200_OK)
def delete_cluster(cluster_id: int):
    db = SessionLocal()
    try:
        cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Кластер не найден")
        
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
    finally:
        db.close()
