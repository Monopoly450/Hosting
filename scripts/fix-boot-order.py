import sys
import logging
from kubernetes import client, config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fix-boot-order")

def main():
    logger.info("Подключение к API Kubernetes...")
    try:
        config.load_kube_config(config_file="/root/.kube/config")
    except Exception:
        try:
            config.load_incluster_config()
        except Exception:
            try:
                config.load_kube_config()
            except Exception as e:
                logger.error(f"Не удалось подключиться к кластеру: {e}")
                sys.exit(1)

    custom_api = client.CustomObjectsApi()
    
    vms = ["pve-node01", "pve-node02"]
    for vm_name in vms:
        logger.info(f"Получение конфигурации ВМ: {vm_name}...")
        try:
            vm = custom_api.get_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace="default",
                plural="virtualmachines",
                name=vm_name
            )
            
            devices = vm["spec"]["template"]["spec"]["domain"].get("devices", {})
            disks = devices.get("disks", [])
            modified = False
            
            for disk in disks:
                if disk.get("name") == "winhd":
                    # Устанавливаем жесткий диск первым в порядке загрузки
                    disk["bootOrder"] = 1
                    modified = True
                    logger.info(f"[{vm_name}] Установлен bootOrder=1 для winhd")
                elif disk.get("name") == "winiso":
                    # Устанавливаем установочный ISO вторым
                    disk["bootOrder"] = 2
                    modified = True
                    logger.info(f"[{vm_name}] Установлен bootOrder=2 для winiso")
            
            if modified:
                # Патчим манифест
                custom_api.patch_namespaced_custom_object(
                    group="kubevirt.io",
                    version="v1",
                    namespace="default",
                    plural="virtualmachines",
                    name=vm_name,
                    body={"spec": vm["spec"]}
                )
                logger.info(f"[{vm_name}] Конфигурация успешно обновлена в Kubernetes.")
            else:
                logger.warning(f"[{vm_name}] Диски winhd/winiso не найдены в конфигурации.")
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении ВМ {vm_name}: {e}")

if __name__ == "__main__":
    main()
