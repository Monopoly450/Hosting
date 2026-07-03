import os
import shutil
import subprocess
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends
from app.core.k8s_client import K8sClient
from kubernetes.client.rest import ApiException
from app.db import SessionLocal
from app.models.models import VMTask, User
from app.core.auth import get_current_user

router = APIRouter()

import time

_lvm_cache = {
    "data": {"total_gb": 0.0, "free_gb": 0.0, "used_gb": 0.0},
    "last_updated": 0.0
}

def get_k8s_client():
    return K8sClient()

@router.get("/metrics")
def get_host_metrics(client: K8sClient = Depends(get_k8s_client)):
    """Возвращает общую емкость сервера и текущую нагрузку (CPU, RAM) из K8s Node API, а также резервирование ВМ и диски"""
    try:
        nodes = client.core_api.list_node()
        if not nodes.items:
            raise HTTPException(status_code=404, detail="Ноды Kubernetes не найдены")
            
        node = nodes.items[0] # Берем первую (и единственную в K3s) ноду
        node_name = node.metadata.name
        
        # Get host CPU model and socket count
        cpu_model = "Unknown Processor"
        physical_ids = set()
        if os.path.exists("/proc/cpuinfo"):
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "model name" in line:
                            cpu_model = line.split(":", 1)[1].strip()
                        elif "physical id" in line:
                            physical_ids.add(line.split(":", 1)[1].strip())
            except Exception:
                pass
        cpu_sockets = len(physical_ids) if physical_ids else 1

        # Емкость хоста
        capacity = node.status.capacity
        allocatable = node.status.allocatable
        
        # Парсинг CPU (например, '8')
        cpu_capacity = int(capacity.get("cpu", 1))
        
        # Парсинг RAM (например, '74123456Ki')
        def parse_k8s_mem(mem_str):
            if not mem_str:
                return 0
            if mem_str.endswith("Ki"):
                return int(mem_str[:-2]) * 1024
            elif mem_str.endswith("Mi"):
                return int(mem_str[:-2]) * 1024 * 1024
            elif mem_str.endswith("Gi"):
                return int(mem_str[:-2]) * 1024 * 1024 * 1024
            return int(mem_str)
            
        mem_capacity_bytes = parse_k8s_mem(capacity.get("memory"))
        mem_allocatable_bytes = parse_k8s_mem(allocatable.get("memory"))
        
        # Текущая загрузка из metrics.k8s.io
        cpu_usage_milli = 0
        mem_usage_bytes = 0
        
        try:
            node_metrics = client.custom_api.get_cluster_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                plural="nodes",
                name=node_name
            )
            
            # Парсинг текущего CPU (в нс или милликорах)
            cpu_usage_str = node_metrics.get("usage", {}).get("cpu", "0n")
            if cpu_usage_str.endswith("n"):
                cpu_usage_milli = int(cpu_usage_str[:-1]) / 1000000
            elif cpu_usage_str.endswith("u"):
                cpu_usage_milli = int(cpu_usage_str[:-1]) / 1000
            elif cpu_usage_str.endswith("m"):
                cpu_usage_milli = int(cpu_usage_str[:-1])
            else:
                cpu_usage_milli = int(cpu_usage_str) * 1000
                
            # Парсинг текущей RAM
            mem_usage_str = node_metrics.get("usage", {}).get("memory", "0Ki")
            mem_usage_bytes = parse_k8s_mem(mem_usage_str)
            
        except ApiException:
            # Если метрики временно недоступны
            pass

        # Дисковое пространство         # Вычисляем зарезервированные ресурсы ВМ в базе данных
        reserved_cpu_cores = 0
        reserved_ram_gb = 0
        reserved_disk_gb = 0
        reserved_stopped_ram_gb = 0

        db = SessionLocal()
        try:
            # 1. Выполняем синхронизацию и очистку в изолированном try-except, чтобы не поломать выдачу метрик
            try:
                # Безопасно получаем список ВМ из K8s
                all_k8s_vms = client.list_vms()
                k8s_vm_map = {v["name"]: v for v in all_k8s_vms}
                
                if k8s_vm_map is not None:
                    from app.models.models import User, UserDatabase, UserVolume
                    db_vms = db.query(VMTask).all()
                    
                    # Удаляем только не создающиеся (не Pending/Provisioning) записи, которых нет в K8s
                    for vm in db_vms:
                        if vm.status not in ["Pending", "Provisioning"] and vm.name not in k8s_vm_map:
                            # Безопасно отвязываем базы данных и сетевые диски
                            db.query(UserDatabase).filter(UserDatabase.associated_vm_id == vm.id).update({"associated_vm_id": None})
                            db.query(UserVolume).filter(UserVolume.attached_vm_id == vm.id).update({"attached_vm_id": None})
                            db.delete(vm)
                    db.commit()

                    # Воссоздаем записи для ВМ, которые есть в K8s, но отсутствуют в БД (после случайного удаления)
                    users = db.query(User).all()
                    student_users = [u for u in users if u.role != "admin"]
                    admin_user = next((u for u in users if u.role == "admin"), None)
                    default_owner_id = student_users[0].id if student_users else (admin_user.id if admin_user else 1)

                    db_vms = db.query(VMTask).all()
                    db_vm_names = {vm.name for vm in db_vms}

                    for name, k8s_vm in k8s_vm_map.items():
                        if name not in db_vm_names:
                            cpu_cores = k8s_vm.get("cpu_cores", 1)
                            
                            mem_str = k8s_vm.get("memory", "1Gi")
                            memory_gb = 1
                            try:
                                if mem_str.endswith("Gi"):
                                    memory_gb = int(mem_str[:-2])
                                elif mem_str.endswith("Mi"):
                                    memory_gb = int(mem_str[:-2]) // 1024
                            except Exception:
                                pass
                            
                            disk_gb = 10
                            disks = k8s_vm.get("disks", [])
                            if disks:
                                size_str = disks[0].get("size", "10Gi")
                                try:
                                    if size_str.endswith("Gi"):
                                        disk_gb = int(size_str[:-2])
                                    elif size_str.endswith("Mi"):
                                        disk_gb = int(size_str[:-2]) // 1024
                                  except Exception:
                                    pass

                            owner_id = default_owner_id
                            for u in users:
                                if u.username.lower() in name.lower():
                                    owner_id = u.id
                                    break

                            new_task = VMTask(
                                name=name,
                                os_type=k8s_vm.get("os_type", "ubuntu"),
                                cpu_cores=cpu_cores,
                                memory_gb=memory_gb,
                                disk_gb=disk_gb,
                                status="Running",
                                owner_id=owner_id
                            )
                            db.add(new_task)
                    db.commit()
            except Exception as sync_err:
                db.rollback()
                import logging
                logging.getLogger("app.host").error(f"Error during VMTask database sync: {sync_err}")

            # 2. Подсчитываем реальные зарезервированные ресурсы
            try:
                db_vms = db.query(VMTask).all()
                reserved_cpu_cores = sum(vm.cpu_cores for vm in db_vms)
                reserved_ram_gb = sum(vm.memory_gb for vm in db_vms)
                reserved_disk_gb = sum(vm.disk_gb for vm in db_vms)
                reserved_stopped_ram_gb = sum(vm.memory_gb for vm in db_vms if vm.status != "Running")
            except Exception as calc_err:
                reserved_stopped_ram_gb = 0
                import logging
                logging.getLogger("app.host").error(f"Error calculating VMTask resource stats: {calc_err}")
                
        except Exception as global_err:
            import logging
            logging.getLogger("app.host").error(f"Global error in DB block of host metrics: {global_err}")
        finally:
            db.close()

        # Дисковое пространство на локальном сервере (SSD хоста)
        local_total, local_used, local_free = shutil.disk_usage("/")
        local_disk = {
            "total_gb": round(local_total / (1024**3), 1),
            "used_gb": round(local_used / (1024**3), 1),
            "free_gb": round(local_free / (1024**3), 1),
            "used_percent": round(local_used / local_total * 100, 1)
        }

        # Дисковое пространство на СХД (NFS)
        shared_disk = {
            "active": False,
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "used_percent": 0.0
        }
        if os.path.exists("/mnt/shared-pvc"):
            try:
                sh_total, sh_used, sh_free = shutil.disk_usage("/mnt/shared-pvc")
                if sh_total > 0:
                    shared_disk = {
                        "active": True,
                        "total_gb": round(sh_total / (1024**3), 1),
                        "used_gb": round(sh_used / (1024**3), 1),
                        "free_gb": round(sh_free / (1024**3), 1),
                        "used_percent": round(sh_used / sh_total * 100, 1)
                    }
            except Exception:
                pass

        # Получаем данные LVM пула vg-aegis с кэшированием на 15 секунд и таймаутом
        global _lvm_cache
        now = time.time()
        if now - _lvm_cache["last_updated"] >= 15.0:
            lvm_info = {"total_gb": 0.0, "free_gb": 0.0, "used_gb": 0.0}
            try:
                res = subprocess.run(
                    ["vgs", "--units", "g", "--nosuffix", "--noheadings", "-o", "vg_size,vg_free", "vg-aegis"],
                    capture_output=True,
                    text=True,
                    timeout=2.0
                )
                if res.returncode == 0:
                    parts = res.stdout.strip().split()
                    if len(parts) >= 2:
                        vg_size = float(parts[0].replace(",", "."))
                        vg_free = float(parts[1].replace(",", "."))
                        lvm_info = {
                            "total_gb": round(vg_size, 1),
                            "free_gb": round(vg_free, 1),
                            "used_gb": round(vg_size - vg_free, 1)
                        }
            except Exception as lvm_err:
                import logging
                logging.getLogger("app.host").error(f"Failed to query LVM vg-aegis info: {lvm_err}")

            # Резервный вариант: если LVM пуст, показываем СХД
            if lvm_info["total_gb"] == 0.0 and shared_disk["active"]:
                lvm_info = {
                    "total_gb": shared_disk["total_gb"],
                    "free_gb": shared_disk["free_gb"],
                    "used_gb": shared_disk["used_gb"]
                }

            _lvm_cache["data"] = lvm_info
            _lvm_cache["last_updated"] = now

        lvm_info = _lvm_cache["data"]

        # Получаем данные о кластере и нодах
        nodes_list = []
        is_cluster = len(nodes.items) > 1

        total_cores = 0
        total_used_cores = 0.0
        total_ram_bytes = 0
        total_used_ram_bytes = 0

        for n in nodes.items:
            n_name = n.metadata.name
            
            n_status = "Unknown"
            for cond in n.status.conditions:
                if cond.type == "Ready":
                    n_status = "Ready" if cond.status == "True" else "NotReady"
                    break
                    
            n_role = "Worker"
            for label in n.metadata.labels:
                if "control-plane" in label or "master" in label:
                    n_role = "Master"
                    break
                    
            n_ip = "Unknown"
            if n.status.addresses:
                for addr in n.status.addresses:
                    if addr.type == "InternalIP":
                        n_ip = addr.address
                        break
                        
            n_cpu_capacity = int(n.status.capacity.get("cpu", 1))
            n_mem_capacity = parse_k8s_mem(n.status.capacity.get("memory"))
            
            n_cpu_usage_milli = 0
            n_mem_usage_bytes = 0
            
            try:
                n_metrics = client.custom_api.get_cluster_custom_object(
                    group="metrics.k8s.io",
                    version="v1beta1",
                    plural="nodes",
                    name=n_name
                )
                
                cpu_str = n_metrics.get("usage", {}).get("cpu", "0n")
                if cpu_str.endswith("n"):
                    n_cpu_usage_milli = int(cpu_str[:-1]) / 1000000
                elif cpu_str.endswith("u"):
                    n_cpu_usage_milli = int(cpu_str[:-1]) / 1000
                elif cpu_str.endswith("m"):
                    n_cpu_usage_milli = int(cpu_str[:-1])
                else:
                    n_cpu_usage_milli = int(cpu_str) * 1000
                    
                mem_str = n_metrics.get("usage", {}).get("memory", "0Ki")
                n_mem_usage_bytes = parse_k8s_mem(mem_str)
            except Exception:
                pass
                
            n_usage_cores = round(n_cpu_usage_milli / 1000, 2)
            n_usage_ram_gb = round(n_mem_usage_bytes / (1024**3), 2)
            n_total_ram_gb = round(n_mem_capacity / (1024**3), 2)

            # Суммируем ресурсы для кластера
            if n_status == "Ready":
                total_cores += n_cpu_capacity
                total_used_cores += n_usage_cores
                total_ram_bytes += n_mem_capacity
                total_used_ram_bytes += n_mem_usage_bytes

            nodes_list.append({
                "name": n_name,
                "status": n_status,
                "role": n_role,
                "ip": n_ip,
                "cpu": {
                    "total_cores": n_cpu_capacity,
                    "usage_cores": n_usage_cores,
                    "usage_percent": round(n_usage_cores / n_cpu_capacity * 100, 1) if n_cpu_capacity else 0,
                    "model": cpu_model if n_role == "Master" else "Cluster Node vCPU"
                },
                "memory": {
                    "total_gb": n_total_ram_gb,
                    "usage_gb": n_usage_ram_gb,
                    "usage_percent": round(n_usage_ram_gb / n_total_ram_gb * 100, 1) if n_total_ram_gb else 0
                }
            })

        # Если это не кластер, или если суммирование дало 0 (все упали), откатываемся к локальной ноде
        if not is_cluster or total_cores == 0:
            total_cores = cpu_capacity
            total_used_cores = round(cpu_usage_milli / 1000, 2)
            total_ram_bytes = mem_capacity_bytes
            total_used_ram_bytes = mem_usage_bytes

        cluster_ram_gb = round(total_ram_bytes / (1024**3), 2)
        cluster_used_ram_gb = round(total_used_ram_bytes / (1024**3), 2)

        return {
            "node_name": node_name,
            "is_cluster": is_cluster,
            "nodes_list": nodes_list,
            "local_disk": local_disk,
            "shared_disk": shared_disk,
            "lvm": lvm_info,
            "cpu": {
                "total_cores": total_cores,
                "usage_cores": round(total_used_cores, 2),
                "usage_percent": round(total_used_cores / total_cores * 100, 1) if total_cores else 0,
                "reserved_cores": reserved_cpu_cores,
                "available_cores": max(0, total_cores - reserved_cpu_cores),
                "model": cpu_model,
                "sockets": cpu_sockets
            },
            "memory": {
                "total_gb": cluster_ram_gb,
                "allocatable_gb": round(mem_allocatable_bytes / (1024**3), 2) if not is_cluster else round(cluster_ram_gb * 0.9, 2),
                "usage_gb": cluster_used_ram_gb,
                "usage_percent": round(total_used_ram_bytes / total_ram_bytes * 100, 1) if total_ram_bytes else 0,
                "reserved_gb": reserved_ram_gb,
                "available_gb": max(0.0, round(cluster_ram_gb - cluster_used_ram_gb - reserved_stopped_ram_gb, 2))
            },
            "disk": {
                "total_gb": shared_disk["total_gb"] if shared_disk["active"] else local_disk["total_gb"],
                "used_gb": shared_disk["used_gb"] if shared_disk["active"] else local_disk["used_gb"],
                "free_gb": shared_disk["free_gb"] if shared_disk["active"] else local_disk["free_gb"],
                "used_percent": shared_disk["used_percent"] if shared_disk["active"] else local_disk["used_percent"],
                "reserved_gb": reserved_disk_gb,
                "available_gb": max(0.0, shared_disk["free_gb"] if shared_disk["active"] else local_disk["free_gb"])
            },
            "os_info": node.status.node_info.os_image,
            "kernel_version": node.status.node_info.kernel_version,
            "kubelet_version": node.status.node_info.kubelet_version,
            "container_runtime": node.status.node_info.container_runtime_version,
            "architecture": node.status.node_info.architecture,
            "operating_system": node.status.node_info.operating_system,
            "system_uuid": node.status.node_info.system_uuid
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class StorageResizeRequest(BaseModel):
    size_gb: int

@router.post("/storage/resize")
def resize_lvm_storage(req: StorageResizeRequest, current_user: User = Depends(get_current_user)):
    """Изменение размера блочного LVM хранилища на хосте (только для администраторов)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора.")

    if req.size_gb <= 0:
        raise HTTPException(status_code=400, detail="Размер должен быть положительным числом.")

    image_path = "/var/lib/aegis/lvm-storage.img"
    
    # 1. Проверяем существование файла-образа
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Файл-образ хранилища {image_path} не найден на хосте.")

    # 2. Определяем текущий размер файла в ГБ
    try:
        current_bytes = os.path.getsize(image_path)
        current_gb = round(current_bytes / (1024**3), 1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось определить текущий размер файла-образа: {e}")

    if req.size_gb == current_gb:
        return {
            "status": "success",
            "message": f"Размер хранилища уже равен {req.size_gb} ГБ.",
            "current_size_gb": req.size_gb
        }

    # 3. Выполняем изменение размера
    try:
        # Находим петлевое устройство (loopback device)
        find_loop = subprocess.run(
            ["losetup", "-j", image_path], 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        if not find_loop.stdout.strip():
            raise Exception("Устройство loop device для файла-образа не найдено в ОС.")
            
        loop_dev = find_loop.stdout.split(":")[0].strip()

        if req.size_gb < current_gb:
            # СЖАТИЕ ХРАНИЛИЩА (Shrink)
            # Сначала уменьшаем размер физического тома LVM.
            # Если на диске есть распределенные тома ВМ, выходящие за новые рамки, LVM вернет ошибку и прервет операцию.
            pv_resize = subprocess.run(
                ["pvresize", "--yes", "--setphysicalvolumesize", f"{req.size_gb}G", loop_dev],
                capture_output=True,
                text=True
            )
            if pv_resize.returncode != 0:
                error_msg = pv_resize.stderr or pv_resize.stdout
                raise Exception(f"LVM отказался сжимать диск (возможно, занятые блоки выходят за указанный размер): {error_msg.strip()}")
                
            # Сообщаем ядру об изменении размера loop-устройства
            subprocess.run(["losetup", "-c", loop_dev], check=True)
            
            # Урезаем сам файл-образ на хосте до нового размера
            subprocess.run(["truncate", "-s", f"{req.size_gb}G", image_path], check=True)
            
            action_name = "уменьшено"
        else:
            # РАСШИРЕНИЕ ХРАНИЛИЩА (Expand)
            # Сначала расширяем файл-образ
            subprocess.run(["truncate", "-s", f"{req.size_gb}G", image_path], check=True)
            # Сообщаем ядру об изменении размера loop-устройства
            subprocess.run(["losetup", "-c", loop_dev], check=True)
            # Расширяем физический том LVM
            subprocess.run(["pvresize", loop_dev], check=True)
            
            action_name = "расширено"
            
        return {
            "status": "success",
            "message": f"Блочное хранилище успешно {action_name} с {current_gb} ГБ до {req.size_gb} ГБ.",
            "current_size_gb": req.size_gb
        }
            
    except subprocess.CalledProcessError as sub_err:
        err_msg = sub_err.stderr or str(sub_err)
        raise HTTPException(
            status_code=500, 
            detail=f"Системная ошибка выполнения команды: {err_msg}"
        )
    except Exception as err:
        raise HTTPException(
            status_code=500, 
            detail=f"Не удалось изменить размер блочного пула: {err}"
        )
