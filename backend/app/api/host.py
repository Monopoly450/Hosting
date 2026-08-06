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
from app.core.config import settings

router = APIRouter()

import time

_lvm_cache = {
    "data": {"active": False, "total_gb": 0.0, "free_gb": 0.0, "used_gb": 0.0},
    "last_updated": 0.0
}


def host_run(cmd: list, check: bool = False, timeout: float = 60.0):
    """Выполняет команду в пространстве монтирования ХОСТА.

    Обязательно для всего, что трогает устройства: /dev контейнера — это не
    /dev хоста, там нет ни device-mapper, ни loop-устройств. Изменение размера
    пула запускало pvresize и losetup прямо в контейнере и падало на

        /dev/mapper/control: open failed: Operation not permitted
        Cannot use /dev/loop0 (lost): device not found

    Чтение размеров пула (vgs) через nsenter уже шло — сюда его просто не
    довели. Отдельные привилегии не нужны: у контейнера есть pid: host и
    SYS_ADMIN, тем же приёмом работают правила iptables (см. app/api/vms.py).
    """
    return subprocess.run(
        ["nsenter", "--mount=/proc/1/ns/mnt"] + cmd,
        capture_output=True, text=True, check=check, timeout=timeout,
    )

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
                    from app.models.models import User, UserDatabase, UserVolume, AppDeployment
                    db_vms = db.query(VMTask).all()
                    
                    # Удаляем только не создающиеся (не Pending/Provisioning) записи, которых нет в K8s
                    # Если Pending/Provisioning висит дольше 5 минут и ВМ нет в K8s - это зависшая задача, удаляем её
                    import datetime
                    now_utc = datetime.datetime.utcnow()
                    for vm in db_vms:
                        is_stuck_pending = (
                            vm.status in ["Pending", "Provisioning"] and
                            vm.name not in k8s_vm_map and
                            (vm.created_at is None or (now_utc - vm.created_at).total_seconds() > 300)
                        )
                        if vm.name not in k8s_vm_map and (vm.status not in ["Pending", "Provisioning"] or is_stuck_pending):
                            # Отвязываем ВСЁ, что ссылается на эту ВМ по внешнему
                            # ключу, иначе db.delete падает с ForeignKeyViolation,
                            # commit откатывается и синхронизация статусов ломается
                            # целиком — не только для этой записи.
                            db.query(UserDatabase).filter(UserDatabase.associated_vm_id == vm.id).update({"associated_vm_id": None})
                            db.query(UserVolume).filter(UserVolume.attached_vm_id == vm.id).update({"attached_vm_id": None})
                            # Деплой без своей ВМ работать не может. Запись не удаляем
                            # (это данные пользователя), но помечаем как сломанную —
                            # так видно, что произошло, и её можно удалить вручную.
                            db.query(AppDeployment).filter(AppDeployment.vm_id == vm.id).update(
                                {"vm_id": None, "status": "Error"}
                            )
                            db.delete(vm)
                        elif vm.name in k8s_vm_map:
                            # Обновляем статус в БД на актуальный из K8s
                            k8s_status = k8s_vm_map[vm.name].get("status", "Stopped")
                            if vm.status != k8s_status:
                                vm.status = k8s_status
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

        # Подсчет выделенных ресурсов по типам хранилищ (NFS, LVM, Локальные)
        vms_resources = []
        nfs_reserved = {"cpu_cores": 0, "memory_gb": 0.0, "disk_gb": 0.0}
        lvm_reserved = {"cpu_cores": 0, "memory_gb": 0.0, "disk_gb": 0.0}
        local_reserved = {"cpu_cores": 0, "memory_gb": 0.0, "disk_gb": 0.0}

        try:
            k8s_vms = all_k8s_vms if 'all_k8s_vms' in locals() else client.list_vms()
            for kvm in k8s_vms:
                vm_name = kvm.get("name")
                vm_status = kvm.get("status", "Stopped")
                vm_cores = int(kvm.get("cpu_cores", 1))
                
                vm_mem_bytes = parse_k8s_mem(kvm.get("memory", "1Gi"))
                vm_mem_gb = round(vm_mem_bytes / (1024**3), 1)
                
                vm_disk_gb = 0.0
                vm_storage_class = "unknown"
                for d in kvm.get("disks", []):
                    d_size = d.get("size", "0Gi")
                    if d_size == "Ephemeral":
                        continue
                    d_bytes = parse_k8s_mem(d_size)
                    vm_disk_gb += round(d_bytes / (1024**3), 1)
                    if d.get("storage_class") and d.get("storage_class") != "unknown":
                        vm_storage_class = d.get("storage_class")
                
                vm_node = kvm.get("node", "N/A")
                
                vm_info = {
                    "name": vm_name,
                    "status": vm_status,
                    "cpu_cores": vm_cores,
                    "memory_gb": vm_mem_gb,
                    "disk_gb": vm_disk_gb,
                    "storage_class": vm_storage_class,
                    "node": vm_node
                }
                vms_resources.append(vm_info)
                
                # Группируем резервы по классу хранилища
                if "nfs" in vm_storage_class.lower():
                    nfs_reserved["cpu_cores"] += vm_cores
                    nfs_reserved["memory_gb"] += vm_mem_gb
                    nfs_reserved["disk_gb"] += vm_disk_gb
                elif "lvm" in vm_storage_class.lower() or "vg-" in vm_storage_class.lower():
                    lvm_reserved["cpu_cores"] += vm_cores
                    lvm_reserved["memory_gb"] += vm_mem_gb
                    lvm_reserved["disk_gb"] += vm_disk_gb
                else:
                    local_reserved["cpu_cores"] += vm_cores
                    local_reserved["memory_gb"] += vm_mem_gb
                    local_reserved["disk_gb"] += vm_disk_gb

                    
            for r_dict in [nfs_reserved, lvm_reserved, local_reserved]:
                r_dict["memory_gb"] = round(r_dict["memory_gb"], 1)
                r_dict["disk_gb"] = round(r_dict["disk_gb"], 1)
                
        except Exception as vms_err:
            import logging
            logging.getLogger("app.host").error(f"Error querying VMs for early breakdown: {vms_err}")

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
        
        # Автоматическое монтирование NFS для получения реального размера
        nfs_mount_dir = "/mnt/shared-pvc"
        try:
            # Найдем NFS IP из PV
            nfs_ip = None
            try:
                pvs = client.core_api.list_persistent_volume()
                for pv in pvs.items:
                    if pv.spec.nfs:
                        nfs_ip = pv.spec.nfs.server
                        break
            except Exception:
                pass
            
            if nfs_ip:
                os.makedirs(nfs_mount_dir, exist_ok=True)
                if not os.path.ismount(nfs_mount_dir):
                    subprocess.run(
                        ["mount", "-t", "nfs", "-o", "nolock,timeout=3", f"{nfs_ip}:/mnt/shared-pvc", nfs_mount_dir],
                        capture_output=True,
                        timeout=5
                    )
        except Exception:
            pass

        if os.path.exists(nfs_mount_dir):
            try:
                sh_total, sh_used, sh_free = shutil.disk_usage(nfs_mount_dir)
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

        # Если NFS не смонтирован на хосте, но в кластере есть запущенные ВМ на NFS (СХД),
        # считаем СХД активным с виртуальным лимитом 500 ГБ для наглядности
        if not shared_disk["active"] and nfs_reserved["disk_gb"] > 0:
            nfs_total = 500.0
            nfs_used = min(nfs_reserved["disk_gb"], nfs_total)
            shared_disk = {
                "active": True,
                "total_gb": nfs_total,
                "used_gb": nfs_used,
                "free_gb": round(nfs_total - nfs_used, 1),
                "used_percent": round((nfs_used / nfs_total) * 100, 1) if nfs_total > 0 else 0.0
            }

        # Получаем данные LVM пула vg-aegis с кэшированием на 15 секунд и таймаутом
        global _lvm_cache
        now = time.time()
        if now - _lvm_cache["last_updated"] >= 15.0:
            lvm_info = {"active": False, "total_gb": 0.0, "free_gb": 0.0, "used_gb": 0.0, "reserved_gb": 0.0}

            from app.core import capacity as _cap

            # STORAGE_CLASS — одна настройка на весь сервер, и её же читают
            # диск ВМ, бэкап, сетевой диск и приватная база данных (все они
            # используют её при создании PVC). Если она указывает не на LVM,
            # ни один из этих PVC на vg-aegis не попадает — и «зарезервировано»
            # для этой карточки честно равно нулю, что бы ни лежало в БД.
            total_lvm_reserved = 0.0
            if _cap.is_lvm_storage_class(settings.STORAGE_CLASS):
                try:
                    db_lvm = SessionLocal()
                    try:
                        total_lvm_reserved = _cap.known_storage_reservations_gb(db_lvm, k8s=client)
                    finally:
                        db_lvm.close()
                except Exception as res_err:
                    import logging
                    logging.getLogger("app.host").error(f"Не удалось посчитать резерв LVM: {res_err}")

            # Чтение vgs вынесено в app.core.capacity — тот же nsenter-приём,
            # что и здесь раньше, но теперь в одном месте: этим же кодом
            # пользуется и проверка вместимости при создании дисков.
            pool = _cap.read_lvm_pool_gb()
            if pool["active"]:
                vg_size, vg_free = pool["total_gb"], pool["free_gb"]
                physical_used = vg_size - vg_free
                # Используем максимум из физически занятого и логически зарезервированного,
                # так как thin provisioning скрывает реальное использование
                effective_used = max(physical_used, total_lvm_reserved)
                effective_used = min(effective_used, vg_size)  # не больше общего размера
                effective_free = max(0.0, vg_size - effective_used)
                lvm_info = {
                    "active": True,
                    "total_gb": round(vg_size, 1),
                    "free_gb": round(effective_free, 1),
                    "used_gb": round(effective_used, 1),
                    "reserved_gb": round(total_lvm_reserved, 1)
                }

            # Резервный вариант 1: если vgs не сработал, но есть файл-образ LVM на хосте
            if not lvm_info["active"] and os.path.exists("/var/lib/aegis/lvm-storage.img"):
                try:
                    file_size = os.path.getsize("/var/lib/aegis/lvm-storage.img")
                    total_gb = round(file_size / (1024**3), 1)
                    used_gb = min(total_lvm_reserved, total_gb)
                    free_gb = max(0.0, round(total_gb - used_gb, 1))
                    lvm_info = {
                        "active": True,
                        "total_gb": total_gb,
                        "free_gb": free_gb,
                        "used_gb": round(used_gb, 1),
                        "reserved_gb": round(total_lvm_reserved, 1)
                    }
                except Exception as f_err:
                    import logging
                    logging.getLogger("app.host").error(f"Failed to read loopback file size: {f_err}")

            # Резервный вариант 2: если LVM пуст, показываем СХД
            if not lvm_info["active"] and shared_disk["active"]:
                lvm_info = {
                    "active": False,
                    "total_gb": shared_disk["total_gb"],
                    "free_gb": shared_disk["free_gb"],
                    "used_gb": shared_disk["used_gb"],
                    "reserved_gb": 0.0
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

            # Вычисляем диск для каждой ноды
            n_disk_capacity = parse_k8s_mem(n.status.capacity.get("ephemeral-storage"))
            n_disk_allocatable = parse_k8s_mem(n.status.allocatable.get("ephemeral-storage"))
            
            if n_name == node_name:
                n_disk_total_gb = local_disk["total_gb"]
                n_disk_used_gb = local_disk["used_gb"]
                n_disk_free_gb = local_disk["free_gb"]
                n_disk_used_percent = local_disk["used_percent"]
            else:
                n_disk_total_gb = round(n_disk_capacity / (1024**3), 1) if n_disk_capacity else 0.0
                n_disk_free_gb = round(n_disk_allocatable / (1024**3), 1) if n_disk_allocatable else 0.0
                n_disk_used_gb = round(max(0.0, n_disk_total_gb - n_disk_free_gb), 1)
                n_disk_used_percent = round((n_disk_used_gb / n_disk_total_gb * 100), 1) if n_disk_total_gb else 0.0

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
                },
                "disk": {
                    "total_gb": n_disk_total_gb,
                    "used_gb": n_disk_used_gb,
                    "free_gb": n_disk_free_gb,
                    "used_percent": n_disk_used_percent
                }
            })

        # Добавляем СХД ноду в список узлов кластера, если NFS активен
        if is_cluster and shared_disk["active"]:
            nfs_ip = "san-storage"
            try:
                pvs = client.core_api.list_persistent_volume()
                for pv in pvs.items:
                    if pv.spec.nfs:
                        nfs_ip = pv.spec.nfs.server
                        break
            except Exception:
                pass

            # Загружаем реальные метрики CPU/RAM СХД из Prometheus
            prom_cpu_cores = 4
            prom_cpu_load = 8.8
            prom_ram_total = 8.0
            prom_ram_used = 1.44
            
            try:
                # 1. Количество ядер CPU
                cpu_cores_res = client.query_prometheus(f'count(node_cpu_seconds_total{{instance=~"{nfs_ip}:.*", mode="idle"}})')
                if cpu_cores_res and cpu_cores_res.get("status") == "success":
                    result = cpu_cores_res.get("data", {}).get("result", [])
                    if result:
                        prom_cpu_cores = int(result[0]["value"][1])
                
                # 2. Процент загрузки CPU
                cpu_load_res = client.query_prometheus(f'(1 - avg(irate(node_cpu_seconds_total{{instance=~"{nfs_ip}:.*", mode="idle"}}[2m]))) * 100')
                if cpu_load_res and cpu_load_res.get("status") == "success":
                    result = cpu_load_res.get("data", {}).get("result", [])
                    if result:
                        prom_cpu_load = round(float(result[0]["value"][1]), 1)
                
                # 3. Общая RAM
                ram_total_res = client.query_prometheus(f'node_memory_MemTotal_bytes{{instance=~"{nfs_ip}:.*"}}')
                if ram_total_res and ram_total_res.get("status") == "success":
                    result = ram_total_res.get("data", {}).get("result", [])
                    if result:
                        prom_ram_total = round(float(result[0]["value"][1]) / (1024**3), 1)
                        
                # 4. Доступная RAM
                ram_avail_res = client.query_prometheus(f'node_memory_MemAvailable_bytes{{instance=~"{nfs_ip}:.*"}}')
                if ram_avail_res and ram_avail_res.get("status") == "success":
                    result = ram_avail_res.get("data", {}).get("result", [])
                    if result:
                        avail_gb = float(result[0]["value"][1]) / (1024**3)
                        prom_ram_used = round(max(0.0, prom_ram_total - avail_gb), 1)
            except Exception as prom_err:
                import logging
                logging.getLogger("app.host").warning(f"Failed to query SAN storage metrics: {prom_err}")
                
            prom_cpu_usage_cores = round((prom_cpu_load / 100) * prom_cpu_cores, 2)
            prom_ram_used_percent = round((prom_ram_used / prom_ram_total) * 100, 1) if prom_ram_total > 0 else 0.0

            nodes_list.append({
                "name": "san-storage",
                "status": "Ready",
                "role": "Storage (NFS)",
                "ip": nfs_ip,
                "cpu": {
                    "total_cores": prom_cpu_cores,
                    "usage_cores": prom_cpu_usage_cores,
                    "usage_percent": prom_cpu_load,
                    "model": "SAN Intel Xeon"
                },
                "memory": {
                    "total_gb": prom_ram_total,
                    "usage_gb": prom_ram_used,
                    "usage_percent": prom_ram_used_percent
                },
                "disk": {
                    "total_gb": shared_disk["total_gb"],
                    "used_gb": shared_disk["used_gb"],
                    "free_gb": shared_disk["free_gb"],
                    "used_percent": shared_disk["used_percent"]
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

        # Метрики уже вычислены ранее

        return {
            "node_name": node_name,
            "is_cluster": is_cluster,
            "nodes_list": nodes_list,
            "vms_resources": vms_resources,
            "nfs_reserved": nfs_reserved,
            "lvm_reserved": lvm_reserved,
            "local_reserved": local_reserved,
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


@router.get("/prometheus/history")
def get_prometheus_history(hours: int = 3, client: K8sClient = Depends(get_k8s_client)):
    """Возвращает временные ряды CPU и RAM загрузки хоста из Prometheus за последние N часов"""
    import urllib.parse
    
    end_time = int(time.time())
    start_time = end_time - (hours * 3600)
    
    # Определяем шаг на основе диапазона
    if hours <= 1:
        step = "30s"
    elif hours <= 6:
        step = "60s"
    elif hours <= 24:
        step = "300s"
    else:
        step = "600s"
    
    cpu_data = []
    ram_data = []
    
    try:
        # CPU usage % — средняя загрузка CPU по всем ядрам (100% = полная загрузка)
        cpu_query = urllib.parse.quote('100 - (avg(irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)')
        cpu_result = client.query_prometheus(cpu_query, start_time=start_time, end_time=end_time, step=step)
        
        if cpu_result and cpu_result.get("status") == "success":
            results = cpu_result.get("data", {}).get("result", [])
            if results:
                for ts, val in results[0].get("values", []):
                    cpu_data.append({"timestamp": int(ts), "value": round(float(val), 1)})
    except Exception as e:
        import logging
        logging.getLogger("app.host").warning(f"Prometheus CPU query failed: {e}")
    
    try:
        # RAM usage % — процент используемой памяти
        ram_query = urllib.parse.quote('100 - ((node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100)')
        ram_result = client.query_prometheus(ram_query, start_time=start_time, end_time=end_time, step=step)
        
        if ram_result and ram_result.get("status") == "success":
            results = ram_result.get("data", {}).get("result", [])
            if results:
                for ts, val in results[0].get("values", []):
                    ram_data.append({"timestamp": int(ts), "value": round(float(val), 1)})
    except Exception as e:
        import logging
        logging.getLogger("app.host").warning(f"Prometheus RAM query failed: {e}")
    
    return {
        "cpu": cpu_data,
        "ram": ram_data,
        "range_hours": hours,
        "step": step
    }


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
        find_loop = host_run(["losetup", "-j", image_path], check=True)

        if not find_loop.stdout.strip():
            # Не внутренняя ошибка, а состояние хоста: служба aegis-lvm не
            # подняла loop-устройство. 500 здесь маскируется кодом обращения,
            # и пользователь не видит, что именно чинить.
            raise HTTPException(
                status_code=409,
                detail=f"Loop-устройство для {image_path} не подключено. "
                       f"Проверьте службу: systemctl status aegis-lvm")

        loop_dev = find_loop.stdout.split(":")[0].strip()

        if req.size_gb < current_gb:
            # СЖАТИЕ ХРАНИЛИЩА (Shrink)
            # Сначала уменьшаем размер физического тома LVM.
            # Если на диске есть распределенные тома ВМ, выходящие за новые рамки, LVM вернет ошибку и прервет операцию.
            pv_resize = host_run(
                ["pvresize", "--yes", "--setphysicalvolumesize", f"{req.size_gb}G", loop_dev])
            if pv_resize.returncode != 0:
                # Отказ LVM — ожидаемый исход (занятые экстенты за новой
                # границей, метаданные в конце устройства), а не сбой панели.
                # Отдаём 400 с ПОДЛИННЫМ текстом от LVM: как 500 он попадал
                # под маскировку и превращался в «Внутренняя ошибка сервера,
                # код обращения ...», по которому чинить нечего.
                error_msg = (pv_resize.stderr or pv_resize.stdout or "").strip()
                raise HTTPException(
                    status_code=400,
                    detail=f"LVM отказался уменьшать пул до {req.size_gb} ГБ. "
                           f"Ответ LVM: {error_msg or 'без пояснений'}")
                
            # Сообщаем ядру об изменении размера loop-устройства
            host_run(["losetup", "-c", loop_dev], check=True)

            # Урезаем сам файл-образ на хосте до нового размера
            host_run(["truncate", "-s", f"{req.size_gb}G", image_path], check=True)

            action_name = "уменьшено"
        else:
            # РАСШИРЕНИЕ ХРАНИЛИЩА (Expand)
            # Сначала расширяем файл-образ
            host_run(["truncate", "-s", f"{req.size_gb}G", image_path], check=True)
            # Сообщаем ядру об изменении размера loop-устройства
            host_run(["losetup", "-c", loop_dev], check=True)
            # Расширяем физический том LVM
            host_run(["pvresize", loop_dev], check=True)

            action_name = "расширено"
            
        return {
            "status": "success",
            "message": f"Блочное хранилище успешно {action_name} с {current_gb} ГБ до {req.size_gb} ГБ.",
            "current_size_gb": req.size_gb
        }
            
    except HTTPException:
        # Осмысленные отказы (LVM не может сжать, loop не подключён) уже
        # оформлены как 4xx с настоящей причиной — общий обработчик ниже
        # превратил бы их обратно в 500, а 500 маскируется кодом обращения,
        # и пользователь снова остался бы без объяснения.
        raise
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
