import os
import sys
import traceback
import json
import time
import logging
import pika
import threading

def write_crash_log(e):
    trace = traceback.format_exc()
    print("CRASH TRACEBACK:")
    print(trace)
    try:
        with open("/app/data/worker_crash.log", "w") as f:
            f.write(f"Worker crashed at startup:\n{trace}\n")
    except:
        pass

try:
    from sqlalchemy.orm import Session
    from .db import SessionLocal, engine
    from .models.models import VMTask, Cluster
    from .core.database import Base
    from .core.k8s_client import K8sClient

    # Инициализация таблиц
    Base.metadata.create_all(bind=engine)

    RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    k8s = K8sClient()
except Exception as e:
    write_crash_log(e)
    sys.exit(1)

def process_vm_task(db: Session, task_id: int):
    task = db.query(VMTask).filter(VMTask.id == task_id).first()
    if not task:
        logger.error(f"Task {task_id} not found")
        return
    
    try:
        task.status = "Provisioning"
        db.commit()
        
        # Получаем данные о кластере, если ВМ в кластере
        multus_network = None
        if task.cluster_id:
            cluster = db.query(Cluster).filter(Cluster.id == task.cluster_id).first()
            if cluster and cluster.network_name:
                multus_network = cluster.network_name

        logger.info(f"Creating VM {task.name}...")
        
        # Формируем псевдо-request объект для передачи в k8s.create_vm
        class FakeReq:
            name = task.name
            os_type = task.os_type
            cpu_cores = task.cpu_cores
            memory_gb = task.memory_gb
            disk_gb = task.disk_gb
            custom_image = task.custom_image
            packages = task.packages
            network_drives = task.network_drives
            cloud_init_template = task.cloud_init_template
            custom_user_data = task.custom_user_data
        
        # Вызываем логику создания ВМ
        from .api.vms import generate_linux_manifest, generate_windows_manifest, generate_random_password
        
        generated_password = generate_random_password()
        
        if task.os_type in ["ubuntu", "centos", "debian", "bitrix", "custom"]:
            manifest = generate_linux_manifest(FakeReq(), generated_password)
            username = "cloud-user" if task.os_type in ["centos", "bitrix"] else ("debian" if task.os_type == "debian" else "ubuntu")
        elif task.os_type in ["windows", "proxmox"]:
            manifest = generate_windows_manifest(FakeReq())
            username = "Administrator"
        else:
            raise Exception("Неверный тип ОС.")

        # Добавляем сеть кластера если есть
        if multus_network:
            k8s.create_network_attachment_definition(multus_network)
            if "networks" not in manifest["spec"]["template"]["spec"]:
                manifest["spec"]["template"]["spec"]["networks"] = []
            manifest["spec"]["template"]["spec"]["networks"].append({
                "name": "cluster-net",
                "multus": {"networkName": multus_network}
            })
            if "interfaces" not in manifest["spec"]["template"]["spec"]["domain"]["devices"]:
                manifest["spec"]["template"]["spec"]["domain"]["devices"]["interfaces"] = []
            manifest["spec"]["template"]["spec"]["domain"]["devices"]["interfaces"].append({
                "name": "cluster-net",
                "bridge": {}
            })
            
        # Добавляем лимиты диска (Этап 4)
        manifest["spec"]["template"]["spec"]["domain"]["ioThreadsPolicy"] = "shared"
        for disk in manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"]:
            if "disk" in disk:
                disk["disk"]["io"] = "native"
            
        k8s.create_vm_from_manifest(manifest)
        k8s.create_credentials_secret(task.name, username, generated_password)
        
        task.status = "Running"
        db.commit()
        logger.info(f"VM {task.name} created successfully.")
        
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}")
        task.status = "Error"
        task.error_message = str(e)
        db.commit()

def process_attach_network(db: Session, task_id: int, network_name: str):
    task = db.query(VMTask).filter(VMTask.id == task_id).first()
    if not task:
        logger.error(f"Task {task_id} not found")
        return
        
    try:
        logger.info(f"Attaching network {network_name} to VM {task.name}...")
        k8s.create_network_attachment_definition(network_name)
        
        # Получаем манифест ВМ и добавляем сеть
        vm = k8s.custom_api.get_namespaced_custom_object(
            group="kubevirt.io",
            version="v1",
            namespace="default",
            plural="virtualmachines",
            name=task.name
        )
        
        spec = vm["spec"]["template"]["spec"]
        if "networks" not in spec:
            spec["networks"] = []
        
        has_network = any(n.get("name") == "cluster-net" for n in spec["networks"])
        if not has_network:
            spec["networks"].append({
                "name": "cluster-net",
                "multus": {"networkName": network_name}
            })
            if "interfaces" not in spec["domain"]["devices"]:
                spec["domain"]["devices"]["interfaces"] = []
            spec["domain"]["devices"]["interfaces"].append({
                "name": "cluster-net",
                "bridge": {}
            })
            
            k8s.custom_api.replace_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace="default",
                plural="virtualmachines",
                name=task.name,
                body=vm
            )
            
        # Restart VM to apply changes
        k8s.stop_vm(task.name)
        time.sleep(2)
        k8s.start_vm(task.name)
        
        logger.info(f"Successfully attached {network_name} to VM {task.name}")
    except Exception as e:
        logger.error(f"Error attaching network for task {task_id}: {e}")

def callback(ch, method, properties, body):
    data = json.loads(body)
    task_id = data.get("task_id")
    action = data.get("action")
    
    logger.info(f"Received task: {action} for task_id {task_id}")
    
    db = SessionLocal()
    try:
        if action == "create_vm":
            process_vm_task(db, task_id)
        elif action == "attach_network":
            process_attach_network(db, task_id, data.get("network_name"))
        elif action == "delete_vm":
            task = db.query(VMTask).filter(VMTask.id == task_id).first()
            if task:
                k8s.delete_vm(task.name)
        elif action == "delete_cluster_env":
            cluster = db.query(Cluster).filter(Cluster.id == task_id).first()
            if cluster:
                k8s.delete_cluster_env(str(cluster.id))
    finally:
        db.close()
    
    ch.basic_ack(delivery_tag=method.delivery_tag)

def apply_disk_throttling_daemon():
    """Фоновый демон для динамического применения ограничений на дисковый ввод-вывод (cgroups v2)"""
    logger.info("Starting disk throttling daemon thread...")
    while True:
        try:
            db = SessionLocal()
            try:
                vms_in_db = db.query(VMTask).all()
                for vm in vms_in_db:
                    # Проверяем, заданы ли лимиты
                    if not (vm.disk_read_mbs or vm.disk_write_mbs or vm.disk_read_iops or vm.disk_write_iops):
                        continue
                        
                    try:
                        # Получаем информацию о поде ВМ
                        pods = k8s.core_api.list_namespaced_pod(namespace="default", label_selector=f"kubevirt.io/created-by={vm.name}").items
                        if not pods:
                            continue
                            
                        pod = pods[0]
                        pod_uid = pod.metadata.uid
                        if not pod_uid:
                            continue
                            
                        # Переводим дефисы в подчеркивания для соответствия имени systemd slice
                        pod_uid_systemd = pod_uid.replace("-", "_")
                        
                        # Находим мажорный/минорный номера устройства для K3s storage на хосте
                        import subprocess
                        nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
                        stat_res = subprocess.run(nsenter_prefix + ["stat -c '%d' /var/lib/rancher/k3s/storage 2>/dev/null || stat -c '%d' /"], capture_output=True, text=True, timeout=5)
                        if stat_res.returncode != 0:
                            continue
                            
                        dev_id = int(stat_res.stdout.strip())
                        major = (dev_id >> 8) & 0xfff
                        minor = dev_id & 0xff
                        
                        # Строим строку лимита для io.max
                        rbps = f"{vm.disk_read_mbs * 1024 * 1024}" if vm.disk_read_mbs > 0 else "max"
                        wbps = f"{vm.disk_write_mbs * 1024 * 1024}" if vm.disk_write_mbs > 0 else "max"
                        riops = f"{vm.disk_read_iops}" if vm.disk_read_iops > 0 else "max"
                        wiops = f"{vm.disk_write_iops}" if vm.disk_write_iops > 0 else "max"
                        
                        limit_line = f"{major}:{minor} rbps={rbps} wbps={wbps} riops={riops} wiops={wiops}"
                        
                        # Ищем директорию слайса пода
                        find_cmd = f"find /sys/fs/cgroup/kubepods.slice/ -name '*pod{pod_uid_systemd}*.slice' 2>/dev/null"
                        find_res = subprocess.run(nsenter_prefix + [find_cmd], capture_output=True, text=True, timeout=5)
                        if find_res.returncode == 0 and find_res.stdout.strip():
                            pod_slice_paths = find_res.stdout.strip().splitlines()
                            for slice_path in pod_slice_paths:
                                # Ищем все файлы io.max внутри cri-containerd-*.scope контейнеров
                                io_find_cmd = f"find {slice_path} -name 'io.max' 2>/dev/null"
                                io_res = subprocess.run(nsenter_prefix + [io_find_cmd], capture_output=True, text=True, timeout=5)
                                if io_res.returncode == 0 and io_res.stdout.strip():
                                    for io_max_file in io_res.stdout.strip().splitlines():
                                        # Записываем лимит
                                        write_cmd = f"echo '{limit_line}' > {io_max_file}"
                                        subprocess.run(nsenter_prefix + [write_cmd], capture_output=True, timeout=5)
                    except Exception as pe:
                        logger.error(f"Error applying disk limits for VM {vm.name}: {pe}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in disk throttling daemon loop: {e}")
            
        time.sleep(10)

def main():
    logger.info("Starting worker...")
    
    # Запуск фонового демона для ограничения дисков (cgroups v2)
    throttling_thread = threading.Thread(target=apply_disk_throttling_daemon, daemon=True)
    throttling_thread.start()
    
    while True:
        try:
            parameters = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            
            channel.queue_declare(queue='vm_tasks', durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue='vm_tasks', on_message_callback=callback)
            
            logger.info("Waiting for messages in vm_tasks. To exit press CTRL+C")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            logger.error("Connection to RabbitMQ failed, retrying in 5s...")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Worker stopped")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
