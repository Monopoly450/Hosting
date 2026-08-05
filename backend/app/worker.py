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
    from .services.vm_credentials import resolve_vm_password
    from .services.cloudinit import externalize_cloudinit

    # Инициализация таблиц (выполняется бэкендом, убираем для избежания взаимных блокировок)
    # Base.metadata.create_all(bind=engine)

    RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    import hashlib

    def generate_mac_address_cluster(name: str) -> str:
        h = hashlib.md5(name.encode('utf-8')).hexdigest()
        return f"02:00:01:{h[0:2]}:{h[2:4]}:{h[4:6]}"

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
            iso_url = task.iso_url
            ssh_key = task.ssh_key
            static_ip = task.static_ip
            # Сеть кластера прокидываем в манифест — для Linux интерфейс со
            # статическим IP добавит generate_linux_manifest.
            cluster_network = multus_network

        # Вызываем логику создания ВМ
        from .api.vms import generate_linux_manifest, generate_windows_manifest, generate_random_password, default_user_for, generate_mac_address

        # Если cloud-init пришёл извне (деплой, маркетплейс), пароль в него уже
        # вписан, а generate_linux_manifest сгенерированный игнорирует. Тогда в
        # Secret нужно положить именно сохранённый пароль — иначе SSH из панели
        # (логи сборки, терминал, подсказка подключения) не заработает.
        generated_password = resolve_vm_password(task)

        # Windows/Proxmox/TrueNAS ставятся с ISO; всё остальное — Linux-образ с cloud-init
        is_iso = task.os_type in ["windows", "proxmox", "truenas"]
        if is_iso:
            manifest = generate_windows_manifest(FakeReq())
            username = "Administrator"
        else:
            manifest = generate_linux_manifest(FakeReq(), generated_password)
            username = default_user_for(task.os_type)

        # Сеть кластера
        if multus_network:
            k8s.create_network_attachment_definition(multus_network)
            # Для Linux интерфейс кластера (со статическим IP) уже добавлен в манифест.
            # Для ISO-ОС добавляем его вручную (IP настраивается внутри гостя).
            if is_iso:
                spec = manifest["spec"]["template"]["spec"]
                spec.setdefault("networks", []).append({
                    "name": "clusternet",
                    "multus": {"networkName": multus_network}
                })
                spec["domain"]["devices"].setdefault("interfaces", []).append({
                    "name": "clusternet",
                    "bridge": {},
                    "macAddress": generate_mac_address(task.name + "-lan")
                })

        # Добавляем лимиты диска (Этап 4)
        manifest["spec"]["template"]["spec"]["domain"]["ioThreadsPolicy"] = "shared"
        for disk in manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"]:
            if "disk" in disk:
                if disk.get("cache") != "writeback":
                    disk["disk"]["io"] = "native"
            
        # KubeVirt не принимает inline cloud-init больше 2048 байт —
        # выносим его в Secret до создания ВМ.
        externalize_cloudinit(k8s, manifest, task.name)
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

def process_clone_task(db: Session, task_id: int, source_name: str):
    """Клонирует ВМ: создаёт новую с диском-копией исходной (CDI clone из PVC)."""
    task = db.query(VMTask).filter(VMTask.id == task_id).first()
    if not task:
        logger.error(f"Clone task {task_id} not found")
        return

    try:
        task.status = "Provisioning"
        db.commit()
        logger.info(f"Cloning VM {task.name} from {source_name}...")

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
            iso_url = task.iso_url
            ssh_key = task.ssh_key
            static_ip = task.static_ip

        from .api.vms import generate_linux_manifest, generate_windows_manifest, generate_random_password, default_user_for

        # У клона cloud-init копируется из исходной ВМ, поэтому пароль тоже
        # должен браться сохранённый, а не новый (см. resolve_vm_password).
        generated_password = resolve_vm_password(task)

        if task.os_type in ["windows", "proxmox", "truenas"]:
            manifest = generate_windows_manifest(FakeReq())
            username = "Administrator"
            disk_suffix = "hd"
        else:
            manifest = generate_linux_manifest(FakeReq(), generated_password)
            username = default_user_for(task.os_type)
            disk_suffix = "disk"

        # Подменяем источник ОС-диска на клон PVC исходной ВМ
        src_pvc = f"{source_name}-{disk_suffix}"
        tgt_dvt = f"{task.name}-{disk_suffix}"
        swapped = False
        for dvt in manifest["spec"].get("dataVolumeTemplates", []):
            if dvt.get("metadata", {}).get("name") == tgt_dvt:
                dvt["spec"]["source"] = {"pvc": {"namespace": "default", "name": src_pvc}}
                swapped = True
        if not swapped:
            raise Exception(f"Не найден целевой диск {tgt_dvt} для клонирования")

        # Лимиты диска (как при обычном создании)
        manifest["spec"]["template"]["spec"]["domain"]["ioThreadsPolicy"] = "shared"
        for disk in manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"]:
            if "disk" in disk and disk.get("cache") != "writeback":
                disk["disk"]["io"] = "native"

        # KubeVirt не принимает inline cloud-init больше 2048 байт —
        # выносим его в Secret до создания ВМ.
        externalize_cloudinit(k8s, manifest, task.name)
        k8s.create_vm_from_manifest(manifest)
        k8s.create_credentials_secret(task.name, username, generated_password)

        task.status = "Running"
        db.commit()
        logger.info(f"VM {task.name} cloned from {source_name} successfully.")
    except Exception as e:
        logger.error(f"Error cloning task {task_id} from {source_name}: {e}")
        task.status = "Error"
        task.error_message = f"Ошибка клонирования: {e}"
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
                "bridge": {},
                "macAddress": generate_mac_address_cluster(task.name)
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
    # Всё тело обёрнуто в try/except, а ack вызывается в любом случае: иначе
    # «ядовитое» сообщение (битый JSON или упавшая операция) не подтверждается,
    # RabbitMQ шлёт его снова → бесконечный цикл переотправки и падений.
    try:
        data = json.loads(body)
        task_id = data.get("task_id")
        action = data.get("action")
        logger.info(f"Received task: {action} for task_id {task_id}")

        db = SessionLocal()
        try:
            if action == "create_vm":
                process_vm_task(db, task_id)
            elif action == "clone_vm":
                process_clone_task(db, task_id, data.get("source_name"))
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
            else:
                logger.warning(f"Unknown action: {action}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to process message ({body[:200]!r}): {e}")
    finally:
        # Подтверждаем сообщение всегда — не зацикливаемся на сбойных задачах.
        ch.basic_ack(delivery_tag=method.delivery_tag)

def apply_disk_throttling_daemon():
    """Фоновый демон для динамического применения ограничений на дисковый ввод-вывод (cgroups v2)"""
    logger.info("Starting disk throttling daemon thread...")
    while True:
        try:
            vms_data = []
            db = SessionLocal()
            try:
                vms_in_db = db.query(VMTask).all()
                for vm in vms_in_db:
                    # Извлекаем только нужные поля, чтобы закрыть сессию сразу
                    vms_data.append({
                        "name": vm.name,
                        "disk_read_mbs": vm.disk_read_mbs,
                        "disk_write_mbs": vm.disk_write_mbs,
                        "disk_read_iops": vm.disk_read_iops,
                        "disk_write_iops": vm.disk_write_iops
                    })
            finally:
                db.close() # Закрываем транзакцию мгновенно

            for vm in vms_data:
                # Проверяем, заданы ли лимиты
                if not (vm["disk_read_mbs"] or vm["disk_write_mbs"] or vm["disk_read_iops"] or vm["disk_write_iops"]):
                    continue
                    
                try:
                    # Получаем информацию о поде ВМ
                    pods = k8s.core_api.list_namespaced_pod(namespace="default", label_selector=f"kubevirt.io/created-by={vm['name']}").items
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
                    rbps = f"{vm['disk_read_mbs'] * 1024 * 1024}" if vm['disk_read_mbs'] > 0 else "max"
                    wbps = f"{vm['disk_write_mbs'] * 1024 * 1024}" if vm['disk_write_mbs'] > 0 else "max"
                    riops = f"{vm['disk_read_iops']}" if vm['disk_read_iops'] > 0 else "max"
                    wiops = f"{vm['disk_write_iops']}" if vm['disk_write_iops'] > 0 else "max"
                    
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
                    logger.error(f"Error applying disk limits for VM {vm['name']}: {pe}")
        except Exception as e:
            logger.error(f"Error in disk throttling daemon loop: {e}")
            
        time.sleep(10)

def apply_firewall_reconcile_daemon():
    """Следит за IP каждой запущенной ВМ и переустанавливает проброс портов,
    когда IP меняется (в т.ч. после перезагрузки ВМ). Внешние порты стабильны
    (считаются от ID ВМ), поэтому адрес host:port для пользователя не меняется."""
    logger.info("Starting firewall reconcile daemon thread...")
    last_ip = {}  # vm_name -> последний применённый IP
    while True:
        try:
            from .api.vms import (reconcile_vm_firewall_rules, resolve_vm_ports,
                                  read_prerouting_rules, dnat_rules_present)
            from .core.netutils import pick_external_ip

            # Снимок правил на весь проход: одна проверка на цикл вместо
            # одной на каждую ВМ.
            #
            # Доверять только кэшу last_ip нельзя. Правила живут в сетевом
            # пространстве ХОСТА, а кэш — в памяти этого процесса, и они
            # расходятся в обе стороны. Главный случай с живого сервера:
            # Docker переписывает iptables при старте контейнеров, наши
            # DNAT/FORWARD при этом теряются, а IP виртуалки не меняется —
            # значит, по старому условию prev_ip != ip правила не
            # переустанавливались уже никогда, и проброс портов оставался
            # сломанным до перезапуска воркера или смены IP.
            prerouting = read_prerouting_rules()
            vms_data = []
            db = SessionLocal()
            try:
                vms_in_db = db.query(VMTask).all()
                for vm in vms_in_db:
                    vms_data.append({
                        "id": vm.id,
                        "name": vm.name,
                        "ports_config": vm.ports_config,
                        "firewall_rules": vm.firewall_rules,
                        "os_type": vm.os_type
                    })
            finally:
                db.close() # Закрываем транзакцию мгновенно

            live_names = set()
            for vm in vms_data:
                try:
                    info = k8s.get_vm(vm["name"])
                    if info.get("status") != "Running":
                        continue
                    ips = info.get("ips", [])
                    ip = pick_external_ip(ips) if ips else None
                    if not ip:
                        continue
                    live_names.add(vm["name"])
                    prev_ip = last_ip.get(vm["name"])

                    # Переустанавливаем либо при смене IP, либо когда правил
                    # фактически нет в iptables — без лишней «дёрготни», но и
                    # без слепой веры в кэш.
                    reason = None
                    if prev_ip != ip:
                        reason = f"сменился IP (было {prev_ip})" if prev_ip else "первое применение"
                    elif prerouting is not None:
                        ports = resolve_vm_ports(ip, vm["id"], vm["ports_config"], vm["os_type"])
                        if not dnat_rules_present(prerouting, ip, ports):
                            reason = "правила пропали из iptables"

                    if reason:
                        reconcile_vm_firewall_rules(ip, vm["id"], vm["ports_config"], vm["firewall_rules"], vm["os_type"], old_ip=prev_ip)
                        last_ip[vm["name"]] = ip
                        logger.info(f"Firewall re-applied for {vm['name']} -> {ip}: {reason}")
                except Exception as ve:
                    logger.error(f"Firewall reconcile for VM {vm['name']}: {ve}")
            # Забываем IP выключенных/удалённых ВМ, чтобы при новом старте правила переустановились
            for gone in [n for n in last_ip if n not in live_names]:
                del last_ip[gone]
        except Exception as e:
            logger.error(f"Error in firewall reconcile daemon loop: {e}")
        time.sleep(15)


def scheduled_backup_daemon():
    """Планировщик автоматических бэкапов: раз в минуту проверяет расписания
    и запускает бэкапы ВМ/БД, у которых наступил срок, с ротацией старых копий."""
    logger.info("Starting scheduled backup daemon thread...")
    from .services.scheduled_backups import run_due_backups
    while True:
        try:
            run_due_backups(k8s)
        except Exception as e:
            logger.error(f"Error in scheduled backup daemon loop: {e}")
        time.sleep(60)


def stuck_tasks_daemon():
    """Разбирает задачи, зависшие в Pending: очередь могла быть недоступна в
    момент постановки, либо воркер перезапустился после подтверждения
    сообщения. Такая запись занимает квоту, поэтому её нужно закрывать."""
    logger.info("Starting stuck tasks daemon thread...")
    from .services.stuck_tasks import reap_stuck_tasks
    while True:
        try:
            reap_stuck_tasks(k8s)
        except Exception as e:
            logger.error(f"Error in stuck tasks daemon loop: {e}")
        time.sleep(300)


def alerts_daemon():
    """Движок алертов: раз в минуту считывает метрики и шлёт уведомления
    при смене состояния правил (ok<->firing)."""
    logger.info("Starting alerts daemon thread...")
    from .services.alerts import evaluate_alerts
    while True:
        try:
            evaluate_alerts(k8s)
        except Exception as e:
            logger.error(f"Error in alerts daemon loop: {e}")
        time.sleep(60)


def caddy_watchdog_daemon():
    """Лечит зацикленный на перезапуске Caddy сам, без ручного docker rm.

    Обнаружено на живом сервере: Caddy застревал в бесконечном рестарте
    (изначально — из-за конфликта порта с самой панелью, см. build_caddyfile),
    и ничто в панели не вызывало ensure_caddy() повторно, пока не добавляли
    или не проверяли домен вручную. Без доменов — а на свежей установке их
    обычно ещё нет — восстановить панель можно было только зайдя на сервер и
    удалив контейнер руками."""
    logger.info("Starting Caddy watchdog daemon thread...")
    from .services.domains import caddy_watchdog_tick
    while True:
        try:
            caddy_watchdog_tick(k8s)
        except Exception as e:
            logger.error(f"Error in Caddy watchdog daemon loop: {e}")
        time.sleep(60)


def main():
    logger.info("Starting worker...")

    # Запуск фонового демона для ограничения дисков (cgroups v2)
    throttling_thread = threading.Thread(target=apply_disk_throttling_daemon, daemon=True)
    throttling_thread.start()

    # Демон переустановки проброса портов при смене IP ВМ (после перезагрузок)
    firewall_thread = threading.Thread(target=apply_firewall_reconcile_daemon, daemon=True)
    firewall_thread.start()

    # Планировщик запланированных бэкапов
    backup_thread = threading.Thread(target=scheduled_backup_daemon, daemon=True)
    backup_thread.start()

    # Движок алертов и уведомлений
    alerts_thread = threading.Thread(target=alerts_daemon, daemon=True)
    alerts_thread.start()

    # Разбор задач, зависших в Pending
    stuck_thread = threading.Thread(target=stuck_tasks_daemon, daemon=True)
    stuck_thread.start()

    # Вотчдог Caddy: лечит зацикленный на перезапуске контейнер сам
    caddy_thread = threading.Thread(target=caddy_watchdog_daemon, daemon=True)
    caddy_thread.start()

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
