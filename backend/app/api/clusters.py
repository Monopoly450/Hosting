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
        # Кластер создаёт сразу несколько ВМ — считаем их суммарно, под
        # блокировкой строки пользователя (иначе два параллельных создания
        # кластера вместе вышли бы за лимит).
        from app.core.quotas import enforce_quota
        from app.core.ratelimit import check_rate_limit
        from app.core.capacity import lock_host_capacity, ensure_host_capacity
        check_rate_limit(current_user, "create_cluster")

        # Та же проверка «шаблон + ОС», что и при одиночном создании ВМ.
        # Здесь её не было вовсе: несовместимая пара принималась молча,
        # build_template_steps возвращал пустые списки, и ВМ в кластере
        # поднималась «чистой», без обещанного окружения и без ошибки.
        #
        # Проверяем ВСЕ ВМ до создания кластера, а не по ходу цикла ниже:
        # отказ на второй ВМ иначе оставил бы висеть и сам кластер, и уже
        # поставленные в очередь машины.
        from app.services.os_profiles import template_rejection_reason
        for vm in req.vms:
            reason = template_rejection_reason(vm.cloud_init_template, vm.os_type)
            if reason:
                raise HTTPException(status_code=400, detail=f"ВМ «{vm.name}»: {reason}")

        total_vcpus = sum(vm.cpu_cores for vm in req.vms)
        total_ram = sum(vm.memory_gb for vm in req.vms)
        total_disk = sum(vm.disk_gb for vm in req.vms)

        enforce_quota(
            db, current_user,
            add_vms=len(req.vms),
            add_vcpus=total_vcpus,
            add_ram_gb=total_ram,
            add_storage_gb=total_disk,
        )
        # Ресурсы ХОСТА: квота ограничивает пользователя, а это — про то, что
        # железа столько есть. Проверки не было вовсе, и кластер спокойно
        # создавался поверх исчерпанного хоста: ВМ намертво вставали в
        # планировании, а панель показывала «доступно 0».
        #
        # Считаем СУММУ всех ВМ кластера, а не каждую по очереди: по
        # отдельности они пройдут проверку все, а вместе не влезут — ровно так
        # и набирается перерасход. Блокировка до подсчёта, чтобы два
        # параллельных создания кластера не прочитали одно и то же состояние.
        lock_host_capacity(db)
        ensure_host_capacity(db, cpu_cores=total_vcpus,
                             memory_gb=total_ram, disk_gb=total_disk)

        cluster = Cluster(name=req.name, network_name=f"{req.name}-net", owner_id=current_user.id)
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        
        # Добавляем задачи для каждой ВМ:
        for idx, vm_req in enumerate(req.vms):
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
                # СТАТИЧЕСКИЙ IP в изолированной сети кластера — не меняется никогда.
                # 192.168.100.10, .11, .12 ... по порядку ВМ в кластере.
                static_ip=f"192.168.100.{10 + idx}",
                status="Pending"
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            # Порты по умолчанию — как у обычной ВМ (см. default_ports_for).
            # Раньше кластерным ВМ ports_config не проставлялся вообще: в
            # панели список портов оставался пустым, хотя вотчдог всё же
            # создавал правила в iptables по тем же числам. Выглядело это как
            # «в кластере порты не создаются», а на деле расходились интерфейс
            # и система. Считается от ID, поэтому порт стабилен и совпадает с
            # тем, что применит reconcile_vm_firewall_rules.
            import json as _json
            from app.api.vms import default_ports_for
            task.ports_config = _json.dumps(
                default_ports_for(task.id, task.os_type, task.cloud_init_template))
            db.commit()

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
        from app.models.models import UserDatabase, UserVolume, AppDeployment
        for vm in vms:
            # Отправляем задачу на удаление каждой ВМ
            publish_task("vm_tasks", {
                "task_id": vm.id,
                "action": "delete_vm"
            })
            # Отвязываем всё, что ссылается на ВМ по внешнему ключу: иначе
            # удаление кластера падает с ForeignKeyViolation, если к какой-то
            # его машине была привязана БД, сетевой диск или деплой.
            db.query(UserDatabase).filter(UserDatabase.associated_vm_id == vm.id).update({"associated_vm_id": None})
            db.query(UserVolume).filter(UserVolume.attached_vm_id == vm.id).update({"attached_vm_id": None})
            db.query(AppDeployment).filter(AppDeployment.vm_id == vm.id).update(
                {"vm_id": None, "status": "Error"}
            )
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
