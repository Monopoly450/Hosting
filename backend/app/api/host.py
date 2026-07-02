import os
import shutil
from fastapi import APIRouter, HTTPException, Depends
from app.core.k8s_client import K8sClient
from kubernetes.client.rest import ApiException
from app.db import SessionLocal
from app.models.models import VMTask

router = APIRouter()

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

        # Дисковое пространство на хосте
        total, used, free = shutil.disk_usage("/")
        disk_total_gb = round(total / (1024**3), 1)
        disk_used_gb = round(used / (1024**3), 1)
        disk_free_gb = round(free / (1024**3), 1)
        disk_used_percent = round(used / total * 100, 1)

        # Вычисляем зарезервированные ресурсы ВМ в базе данных
        reserved_cpu_cores = 0
        reserved_ram_gb = 0
        reserved_disk_gb = 0

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

        # Инициализируем девелоперские счетчики по умолчанию
        reserved_cpu_cores = 0
        reserved_ram_gb = 0
        reserved_disk_gb = 0

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
                            # Воссоздаем CPU
                            cpu_cores = k8s_vm.get("cpu_cores", 1)
                            
                            # Воссоздаем RAM
                            mem_str = k8s_vm.get("memory", "1Gi")
                            memory_gb = 1
                            try:
                                if mem_str.endswith("Gi"):
                                    memory_gb = int(mem_str[:-2])
                                elif mem_str.endswith("Mi"):
                                    memory_gb = int(mem_str[:-2]) // 1024
                            except Exception:
                                pass
                            
                            # Воссоздаем Disk
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

                            # Угадываем владельца по вхождению его имени в название ВМ
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
            
        total_ram_gb = round(mem_capacity_bytes / (1024 * 1024 * 1024), 2)

        return {
            "node_name": node_name,
            "cpu": {
                "total_cores": cpu_capacity,
                "usage_cores": round(cpu_usage_milli / 1000, 2),
                "usage_percent": round((cpu_usage_milli / 1000) / cpu_capacity * 100, 1) if cpu_capacity else 0,
                "reserved_cores": reserved_cpu_cores,
                "available_cores": max(0, cpu_capacity - reserved_cpu_cores),
                "model": cpu_model,
                "sockets": cpu_sockets
            },
            "memory": {
                "total_gb": total_ram_gb,
                "allocatable_gb": round(mem_allocatable_bytes / (1024 * 1024 * 1024), 2),
                "usage_gb": round(mem_usage_bytes / (1024 * 1024 * 1024), 2),
                "usage_percent": round(mem_usage_bytes / mem_capacity_bytes * 100, 1) if mem_capacity_bytes else 0,
                "reserved_gb": reserved_ram_gb,
                "available_gb": max(0.0, round(total_ram_gb - (mem_usage_bytes / (1024**3)) - reserved_stopped_ram_gb, 2))
            },
            "disk": {
                "total_gb": disk_total_gb,
                "used_gb": disk_used_gb,
                "free_gb": disk_free_gb,
                "used_percent": disk_used_percent,
                "reserved_gb": reserved_disk_gb,
                "available_gb": max(0.0, disk_free_gb)
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
