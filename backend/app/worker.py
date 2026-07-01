import os
import sys
import traceback
import json
import time
import logging
import pika

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
        # Можно добавить delete_vm и т.д.
    finally:
        db.close()
    
    ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    logger.info("Starting worker...")
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
