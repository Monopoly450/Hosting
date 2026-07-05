import logging
import json
import os
import time
import base64
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from app.core.config import settings

logger = logging.getLogger("app.k8s_client")

class K8sClient:
    def __init__(self):
        self.load_config()
        self.core_api = client.CoreV1Api()
        self.custom_api = client.CustomObjectsApi()
        self.api_client = client.ApiClient()

    def load_config(self):
        """Загрузка kubeconfig: пытается использовать ~/.kube/config, /etc/rancher/k3s/k3s.yaml или in-cluster config"""
        try:
            if os.path.exists(settings.KUBECONFIG_PATH):
                logger.info(f"Загрузка kubeconfig из {settings.KUBECONFIG_PATH}")
                config.load_kube_config(config_file=settings.KUBECONFIG_PATH)
            elif os.path.exists(os.path.expanduser("~/.kube/config")):
                logger.info("Загрузка kubeconfig из ~/.kube/config")
                config.load_kube_config()
            elif os.path.exists("/etc/rancher/k3s/k3s.yaml"):
                logger.info("Загрузка kubeconfig из /etc/rancher/k3s/k3s.yaml")
                config.load_kube_config(config_file="/etc/rancher/k3s/k3s.yaml")
            else:
                logger.info("Попытка загрузки in-cluster config...")
                config.load_incluster_config()
            logger.info("Kubernetes API клиент успешно инициализирован.")
        except Exception as e:
            logger.error(f"Ошибка инициализации Kubernetes клиента: {e}")
            raise e

    def get_api_server_info(self):
        """Возвращает хост и параметры авторизации API-сервера для Websocket VNC соединения"""
        conf = self.api_client.configuration
        return {
            "host": conf.host,
            "ssl_ca_cert": conf.ssl_ca_cert,
            "verify_ssl": conf.verify_ssl,
            "api_key": conf.api_key or {},
        }

    # --- УПРАВЛЕНИЕ ВИРТУАЛЬНЫМИ МАШИНАМИ (KubeVirt) ---

    def list_vms(self, namespace="default"):
        """Получить список всех VirtualMachine в пространстве имен"""
        try:
            vms = self.custom_api.list_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines"
            )
            
            # Также получим список запущенных инстансов (VMI), чтобы знать их текущий IP и статус
            vmis = self.custom_api.list_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachineinstances"
            )
            
            vmi_map = {vmi["metadata"]["name"]: vmi for vmi in vmis.get("items", [])}
            
            result = []
            for vm in vms.get("items", []):
                name = vm["metadata"]["name"]
                vmi = vmi_map.get(name)
                
                result.append(self._parse_vm_object(vm, vmi))
                
            return result
        except ApiException as e:
            logger.error(f"Ошибка получения списка VM: {e}")
            raise e

    def get_vm(self, name: str, namespace="default"):
        """Получить детальную информацию о конкретной VM"""
        try:
            vm = self.custom_api.get_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=name
            )
            
            vmi = None
            try:
                vmi = self.custom_api.get_namespaced_custom_object(
                    group="kubevirt.io",
                    version="v1",
                    namespace=namespace,
                    plural="virtualmachineinstances",
                    name=name
                )
            except ApiException as e:
                # Если VM выключена, VMI не существует
                if e.status != 404:
                    raise e
                    
            return self._parse_vm_object(vm, vmi)
        except ApiException as e:
            logger.error(f"Ошибка получения VM {name}: {e}")
            raise e

    def create_vm_from_manifest(self, manifest: dict, namespace="default"):
        """Создать VM из готового словаря-манифеста"""
        try:
            return self.custom_api.create_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                body=manifest
            )
        except ApiException as e:
            logger.error(f"Ошибка создания VM: {e.body}")
            raise e

    def delete_vm(self, name: str, namespace="default"):
        """Удалить VM, ее учетные секреты, связанные диски (DataVolume / PVC) и резервные копии"""
        try:
            # Получаем VM, чтобы узнать имена связанных DataVolume
            vm = self.custom_api.get_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=name
            )
            
            # 1. Удаляем саму VM
            self.custom_api.delete_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=name
            )
            
            # 2. Удаляем Secret с учетными данными
            try:
                self.core_api.delete_namespaced_secret(f"{name}-credentials", namespace)
                logger.info(f"Удален Secret учетных данных для VM: {name}")
            except ApiException as e:
                if e.status != 404:
                    logger.error(f"Не удалось удалить Secret для VM {name}: {e}")
                    
            # 3. Удаляем резервные копии этой VM
            try:
                backups = self.list_vm_backups(name, namespace)
                for backup in backups:
                    self.delete_vm_backup(backup["name"], namespace)
                    logger.info(f"Удалена резервная копия: {backup['name']}")
            except Exception as e:
                logger.error(f"Не удалось удалить бэкапы при удалении VM {name}: {e}")
            
            # 4. Удаляем диски (DataVolume), если они есть в шаблонах
            dvt = vm.get("spec", {}).get("dataVolumeTemplates", [])
            for dv in dvt:
                dv_name = dv["metadata"]["name"]
                try:
                    self.custom_api.delete_namespaced_custom_object(
                        group="cdi.kubevirt.io",
                        version="v1beta1",
                        namespace=namespace,
                        plural="datavolumes",
                        name=dv_name
                    )
                    logger.info(f"Удален DataVolume: {dv_name}")
                except ApiException as e:
                    if e.status != 404:
                        logger.error(f"Не удалось удалить DataVolume {dv_name}: {e}")
            
            # 5. На всякий случай удаляем связанные PVC
            vols = vm.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", [])
            for vol in vols:
                if "persistentVolumeClaim" in vol:
                    pvc_name = vol["persistentVolumeClaim"]["claimName"]
                    try:
                        self.core_api.delete_namespaced_persistent_volume_claim(pvc_name, namespace)
                        logger.info(f"Удален PVC: {pvc_name}")
                    except ApiException as e:
                        if e.status != 404:
                            logger.error(f"Не удалось удалить PVC {pvc_name}: {e}")

            return {"status": "deleted", "name": name}
        except ApiException as e:
            logger.error(f"Ошибка удаления VM {name}: {e}")
            raise e

    # --- УПРАВЛЕНИЕ ПИТАНИЕМ (SUBRESOURCES) ---

    def _call_vms_subresource(self, action: str, name: str, namespace="default"):
        """Вспомогательный метод для вызова API жизненного цикла KubeVirt (start/stop/restart)"""
        try:
            path = f"/apis/subresources.kubevirt.io/v1/namespaces/{namespace}/virtualmachines/{name}/{action}"
            
            # Подготавливаем заголовки авторизации
            headers = {}
            conf = self.api_client.configuration
            if conf.api_key:
                for k, v in conf.api_key.items():
                    headers[k] = v
                    
            response = self.api_client.call_api(
                resource_path=path,
                method="PUT",
                header_params=headers,
                auth_settings=["BearerToken"],
                _return_http_data_only=True
            )
            return {"status": "success", "action": action, "name": name}
        except ApiException as e:
            logger.error(f"Ошибка выполнения действия {action} для VM {name}: {e}")
            raise e

    def start_vm(self, name: str, namespace="default"):
        return self._call_vms_subresource("start", name, namespace)

    def stop_vm(self, name: str, namespace="default"):
        return self._call_vms_subresource("stop", name, namespace)

    def restart_vm(self, name: str, namespace="default"):
        return self._call_vms_subresource("restart", name, namespace)

    # --- СБОР МЕТРИК РЕСУРСОВ ---

    def get_vm_metrics(self, name: str, namespace="default"):
        """Получить метрики использования ресурсов (CPU, RAM) через Metrics API"""
        try:
            pods = self.core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"kubevirt.io/domain={name}"
            )
            
            if not pods.items:
                return {"cpu_usage": 0, "memory_usage": 0, "status": "Stopped"}
                
            pod_name = pods.items[0].metadata.name
            pod_phase = pods.items[0].status.phase
            
            if pod_phase != "Running":
                return {"cpu_usage": 0, "memory_usage": 0, "status": pod_phase}

            try:
                metrics = self.custom_api.get_namespaced_custom_object(
                    group="metrics.k8s.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="pods",
                    name=pod_name
                )
                
                cpu_nano = 0
                mem_bytes = 0
                
                for container in metrics.get("containers", []):
                    cpu_str = container["usage"]["cpu"]
                    mem_str = container["usage"]["memory"]
                    
                    if cpu_str.endswith("n"):
                        cpu_nano += int(cpu_str[:-1])
                    elif cpu_str.endswith("u"):
                        cpu_nano += int(cpu_str[:-1]) * 1000
                    elif cpu_str.endswith("m"):
                        cpu_nano += int(cpu_str[:-1]) * 1000000
                    else:
                        cpu_nano += int(float(cpu_str) * 1000000000)
                        
                    if mem_str.endswith("Ki"):
                        mem_bytes += int(mem_str[:-2]) * 1024
                    elif mem_str.endswith("Mi"):
                        mem_bytes += int(mem_str[:-2]) * 1024 * 1024
                    elif mem_str.endswith("Gi"):
                        mem_bytes += int(mem_str[:-2]) * 1024 * 1024 * 1024
                    elif mem_str.endswith("k"):
                        mem_bytes += int(mem_str[:-1]) * 1000
                    elif mem_str.endswith("m"):
                        mem_bytes += int(mem_str[:-1]) * 1000 * 1000
                    else:
                        mem_bytes += int(mem_str)
                
                cpu_milli = cpu_nano / 1000000
                
                return {
                    "cpu_milli": round(cpu_milli, 2),
                    "memory_bytes": mem_bytes,
                    "memory_mb": round(mem_bytes / (1024 * 1024), 2),
                    "status": "Running"
                }
            except ApiException as e:
                logger.warning(f"Ошибка получения raw-метрик для {pod_name}: {e}")
                return {"cpu_usage_milli": 0, "memory_bytes": 0, "status": "Running (No Metrics)"}
                
        except Exception as e:
            logger.error(f"Не удалось получить метрики для VM {name}: {e}")
            return {"cpu_usage": 0, "memory_usage": 0, "error": str(e)}

    # --- ИЗМЕНЕНИЕ РЕСУРСОВ (CPU, RAM, DISK) ---

    def create_credentials_secret(self, name: str, username: str, password: str, namespace="default"):
        """Создает Secret с учетными данными для виртуалки"""
        try:
            secret_name = f"{name}-credentials"
            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=secret_name,
                    labels={
                        "hosting.antigravity.io/credentials-source": name
                    }
                ),
                string_data={
                    "username": username,
                    "password": password
                }
            )
            self.core_api.create_namespaced_secret(namespace, secret)
            logger.info(f"Создан секрет {secret_name} с учетными данными для ВМ {name} (логин: {username})")
        except Exception as e:
            logger.error(f"Ошибка создания секрета пароля для {name}: {e}")
            raise e

    def resize_vm_resources(self, name: str, cpu_cores: int, memory_gb: int, namespace="default"):
        """Изменяет выделенные ядра CPU и RAM в манифесте VM (требуется перезапуск)"""
        try:
            # Изменяем манифест VM
            body = [
                {"op": "replace", "path": "/spec/template/spec/domain/cpu/cores", "value": cpu_cores},
                {"op": "replace", "path": "/spec/template/spec/domain/resources/requests/memory", "value": f"{memory_gb}Gi"}
            ]
            self.custom_api.patch_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=name,
                body=body
            )
            logger.info(f"Ресурсы VM {name} изменены: CPU={cpu_cores}, RAM={memory_gb}Gi")
            return {"status": "success", "cpu_cores": cpu_cores, "memory_gb": memory_gb}
        except ApiException as e:
            logger.error(f"Ошибка изменения ресурсов VM {name}: {e}")
            raise e

    def resize_vm_disk(self, name: str, new_size_gb: int, namespace="default"):
        """Увеличивает объем системного PVC жесткого диска виртуалки"""
        try:
            # Находим системный PVC по маске имени ВМ
            pvc_list = self.core_api.list_namespaced_persistent_volume_claim(namespace)
            pvc_name = None
            for pvc in pvc_list.items:
                # Нам нужен PVC диска, а не бэкапа
                if pvc.metadata.name.startswith(name) and "-backup-" not in pvc.metadata.name:
                    pvc_name = pvc.metadata.name
                    break
                    
            if not pvc_name:
                raise Exception(f"Системный диск (PVC) для VM {name} не найден.")
                
            body = {
                "spec": {
                    "resources": {
                        "requests": {
                            "storage": f"{new_size_gb}Gi"
                        }
                    }
                }
            }
            self.core_api.patch_namespaced_persistent_volume_claim(pvc_name, namespace, body)
            logger.info(f"Запрос на расширение диска {pvc_name} до {new_size_gb}Gi отправлен.")
            return {"status": "success", "pvc": pvc_name, "new_size_gb": new_size_gb}
        except Exception as e:
            logger.error(f"Ошибка расширения диска для {name}: {e}")
            raise e

    # --- РЕЗЕРВНОЕ КОПИРОВАНИЕ И ВОССТАНОВЛЕНИЕ (BACKUPS) ---

    def create_vm_backup(self, name: str, namespace="default"):
        """Создает бэкап диска (клонирует PVC)"""
        try:
            # Находим системный PVC
            pvc_list = self.core_api.list_namespaced_persistent_volume_claim(namespace)
            orig_pvc_name = None
            orig_pvc = None
            for pvc in pvc_list.items:
                if pvc.metadata.name.startswith(name) and "-backup-" not in pvc.metadata.name:
                    orig_pvc_name = pvc.metadata.name
                    orig_pvc = pvc
                    break
                    
            if not orig_pvc_name:
                raise Exception(f"Оригинальный PVC диска для VM {name} не найден")
                
            # Размер копируемого диска
            storage_size = orig_pvc.spec.resources.requests["storage"]
            
            # Уникальное имя резервной копии
            timestamp = int(time.time())
            backup_name = f"{name}-backup-{timestamp}"
            
            # Создаем DataVolume с источником clone pvc
            dv_manifest = {
                "apiVersion": "cdi.kubevirt.io/v1beta1",
                "kind": "DataVolume",
                "metadata": {
                    "name": backup_name,
                    "namespace": namespace,
                    "labels": {
                        "hosting.antigravity.io/backup-source": name
                    }
                },
                "spec": {
                    "source": {
                        "pvc": {
                            "name": orig_pvc_name,
                            "namespace": namespace
                        }
                    },
                    "storage": {
                        "storageClassName": settings.STORAGE_CLASS,
                        "resources": {
                            "requests": {
                                "storage": storage_size
                            }
                        }
                    }
                }
            }
            
            self.custom_api.create_namespaced_custom_object(
                group="cdi.kubevirt.io",
                version="v1beta1",
                namespace=namespace,
                plural="datavolumes",
                body=dv_manifest
            )
            logger.info(f"Запущен процесс клонирования бэкапа {backup_name} для VM {name}")
            return {"status": "creating", "backup_name": backup_name, "source": orig_pvc_name}
        except Exception as e:
            logger.error(f"Ошибка бэкапа VM {name}: {e}")
            raise e

    def list_vm_backups(self, name: str, namespace="default"):
        """Получить список всех бэкапов для конкретной VM"""
        try:
            dvs = self.custom_api.list_namespaced_custom_object(
                group="cdi.kubevirt.io",
                version="v1beta1",
                namespace=namespace,
                plural="datavolumes",
                label_selector=f"hosting.antigravity.io/backup-source={name}"
            )
            
            backups = []
            for dv in dvs.get("items", []):
                backup_name = dv["metadata"]["name"]
                
                # Статус клонирования
                status = dv.get("status", {}).get("phase", "Unknown")
                progress = dv.get("status", {}).get("progress", "N/A")
                
                size = dv.get("spec", {}).get("storage", {}).get("resources", {}).get("requests", {}).get("storage", "N/A")
                created_at = dv["metadata"].get("creationTimestamp")
                
                backups.append({
                    "name": backup_name,
                    "size": size,
                    "status": status,
                    "progress": progress,
                    "created_at": created_at
                })
            return backups
        except Exception as e:
            logger.error(f"Ошибка получения бэкапов для VM {name}: {e}")
            raise e

    def delete_vm_backup(self, backup_name: str, namespace="default"):
        """Удаляет резервную копию (DataVolume и PVC)"""
        try:
            # Удаляем DataVolume
            self.custom_api.delete_namespaced_custom_object(
                group="cdi.kubevirt.io",
                version="v1beta1",
                namespace=namespace,
                plural="datavolumes",
                name=backup_name
            )
            
            # Удаляем PVC
            try:
                self.core_api.delete_namespaced_persistent_volume_claim(backup_name, namespace)
            except ApiException as e:
                if e.status != 404:
                    raise e
                    
            logger.info(f"Резервная копия {backup_name} удалена.")
            return {"status": "deleted", "backup_name": backup_name}
        except Exception as e:
            logger.error(f"Ошибка удаления бэкапа {backup_name}: {e}")
            raise e

    def restore_vm_backup(self, vm_name: str, backup_name: str, namespace="default"):
        """Заменяет текущий PVC жесткого диска ВМ на клон из выбранного бэкапа"""
        try:
            # 1. Получаем манифест VM
            vm = self.custom_api.get_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=vm_name
            )
            
            # 2. Проверяем, что VM выключена. Иначе останавливаем.
            running = vm.get("spec", {}).get("running", False)
            if running:
                logger.info(f"Авто-остановка VM {vm_name} перед восстановлением...")
                self.stop_vm(vm_name, namespace)
                # Ждем короткое время, чтобы VM выключилась
                time.sleep(2)
            
            # 3. Находим оригинальное имя PVC
            pvc_list = self.core_api.list_namespaced_persistent_volume_claim(namespace)
            orig_pvc_name = None
            for pvc in pvc_list.items:
                if pvc.metadata.name.startswith(vm_name) and "-backup-" not in pvc.metadata.name:
                    orig_pvc_name = pvc.metadata.name
                    break
                    
            if not orig_pvc_name:
                raise Exception(f"Оригинальный системный диск (PVC) для VM {vm_name} не найден.")
                
            # 4. Удаляем старый PVC диска
            try:
                self.core_api.delete_namespaced_persistent_volume_claim(orig_pvc_name, namespace)
                logger.info(f"Старый PVC {orig_pvc_name} удален для замены.")
            except ApiException as e:
                if e.status != 404:
                    raise e
                    
            # Ждем пока PVC удалится
            for _ in range(10):
                try:
                    self.core_api.read_namespaced_persistent_volume_claim(orig_pvc_name, namespace)
                    time.sleep(1)
                except ApiException as e:
                    if e.status == 404:
                        break
            
            # 5. Считываем размер бэкапа
            backup_pvc = self.core_api.read_namespaced_persistent_volume_claim(backup_name, namespace)
            backup_size = backup_pvc.spec.resources.requests["storage"]
            
            # 6. Создаем новый DataVolume с оригинальным именем (orig_pvc_name), клонируя его из бэкапа
            dv_manifest = {
                "apiVersion": "cdi.kubevirt.io/v1beta1",
                "kind": "DataVolume",
                "metadata": {
                    "name": orig_pvc_name,
                    "namespace": namespace
                },
                "spec": {
                    "source": {
                        "pvc": {
                            "name": backup_name,
                            "namespace": namespace
                        }
                    },
                    "storage": {
                        "storageClassName": settings.STORAGE_CLASS,
                        "resources": {
                            "requests": {
                                "storage": backup_size
                            }
                        }
                    }
                }
            }
            
            self.custom_api.create_namespaced_custom_object(
                group="cdi.kubevirt.io",
                version="v1beta1",
                namespace=namespace,
                plural="datavolumes",
                body=dv_manifest
            )
            
            logger.info(f"Восстановление ВМ {vm_name} запущено: {orig_pvc_name} клонируется из {backup_name}")
            return {"status": "restoring", "vm": vm_name, "pvc": orig_pvc_name, "source": backup_name}
        except Exception as e:
            logger.error(f"Ошибка восстановления VM {vm_name} из {backup_name}: {e}")
            raise e

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---

    def _parse_vm_object(self, vm: dict, vmi: dict = None) -> dict:
        """Преобразует сырой манифест KubeVirt в чистый JSON-объект для фронтенда"""
        name = vm["metadata"]["name"]
        namespace = vm["metadata"]["namespace"]
        spec = vm.get("spec", {})
        running_desired = spec.get("running", False)
        
        # Ресурсы
        template_spec = spec.get("template", {}).get("spec", {})
        domain = template_spec.get("domain", {})
        cpu_cores = domain.get("cpu", {}).get("cores", 1)
        
        # Память
        mem_req = domain.get("resources", {}).get("requests", {}).get("memory", "1Gi")
        
        # Диски
        disks = []
        dvt = spec.get("dataVolumeTemplates", [])
        for dv in dvt:
            dv_spec = dv.get("spec", {})
            size = dv_spec.get("storage", {}).get("resources", {}).get("requests", {}).get("storage", "10Gi")
            sc = dv_spec.get("storage", {}).get("storageClassName") or settings.STORAGE_CLASS
            disks.append({
                "name": dv["metadata"]["name"],
                "size": size,
                "storage_class": sc,
                "source": list(dv_spec.get("source", {}).keys())[0] if dv_spec.get("source") else "unknown"
            })
            
        # Дополнительно проверим ephemeral диски (containerDisk)
        volumes = template_spec.get("volumes", [])
        for vol in volumes:
            if "containerDisk" in vol:
                disks.append({
                    "name": vol["name"],
                    "size": "Ephemeral",
                    "source": "containerDisk"
                })

        # Проверяем статус DataVolume
        import_progress = "N/A"
        import_phase = None
        dvt = spec.get("dataVolumeTemplates", [])
        for dv_tmpl in dvt:
            dv_name = dv_tmpl["metadata"]["name"]
            try:
                dv_obj = self.custom_api.get_namespaced_custom_object(
                    group="cdi.kubevirt.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="datavolumes",
                    name=dv_name
                )
                dv_status = dv_obj.get("status", {})
                phase = dv_status.get("phase")
                progress = dv_status.get("progress")
                if phase and phase not in ["Succeeded", "Failed"]:
                    import_phase = phase
                    import_progress = progress or "0%"
                    break
            except Exception as e:
                logger.error(f"Error checking DataVolume {dv_name}: {e}")

        # Получаем данные из запущенного инстанса (VMI)
        status = "Stopped"
        ips = []
        node_name = ""
        creation_timestamp = vm["metadata"].get("creationTimestamp")
        
        if import_phase:
            status = "Importing"
            if vmi:
                node_name = vmi.get("status", {}).get("nodeName", "")
        elif vmi:
            # Если желаемое состояние выключено или VMI удаляется, ставим статус Stopping (Выключение)
            if not running_desired or vmi.get("metadata", {}).get("deletionTimestamp"):
                status = "Stopping"
            else:
                status = vmi.get("status", {}).get("phase", "Unknown")
            node_name = vmi.get("status", {}).get("nodeName", "")
            
            # Собираем IP адреса
            interfaces = vmi.get("status", {}).get("interfaces", [])
            for iface in interfaces:
                ip = iface.get("ipAddress")
                if ip:
                    ips.append(ip)
                for ip_addr in iface.get("ipAddresses", []):
                    if ip_addr not in ips:
                        ips.append(ip_addr)
                        
            # Сохраняем IP в аннотацию, чтобы помнить его после выключения
            if ips:
                main_ip = ips[0]
                annotations = vm.get("metadata", {}).get("annotations", {})
                last_ip = annotations.get("hosting.antigravity.io/last-ip")
                if main_ip != last_ip:
                    try:
                        patch = {"metadata": {"annotations": {"hosting.antigravity.io/last-ip": main_ip}}}
                        self.custom_api.patch_namespaced_custom_object(
                            "kubevirt.io", "v1", "default", "virtualmachines", name, patch
                        )
                    except Exception as e:
                        logger.error(f"Failed to save last-ip for {name}: {e}")
        else:
            if running_desired:
                status = "Starting"
            else:
                status = "Stopped"

        # Если машина выключена и ips пуст, берем из аннотации
        if not ips:
            last_ip = vm.get("metadata", {}).get("annotations", {}).get("hosting.antigravity.io/last-ip")
            if last_ip:
                ips.append(last_ip)

        # Шаблон ОС
        os_type = vm["metadata"].get("labels", {}).get("hosting.antigravity.io/template", "unknown")

        # Получаем учетные данные (логин root/ubuntu + авто-пароль из секретов K8s)
        credentials = {"username": "root", "password": "N/A"}
        try:
            secret = self.core_api.read_namespaced_secret(f"{name}-credentials", namespace)
            pw = base64.b64decode(secret.data["password"]).decode("utf-8")
            credentials["password"] = pw
            if "username" in secret.data:
                credentials["username"] = base64.b64decode(secret.data["username"]).decode("utf-8")
        except Exception:
            pass

        # Вычисляем уникальный порт SSH на основе ID из БД для стабильности
        ssh_port = None
        http_port = None
        https_port = None
        rdp_port = None
        try:
            from app.db import SessionLocal
            from app.models.models import VMTask
            import json
            db = SessionLocal()
            try:
                db_vm = db.query(VMTask).filter(VMTask.name == name).first()
                if db_vm:
                    vm_id = db_vm.id
                    ssh_port = 22000 + vm_id
                    http_port = 28000 + vm_id
                    https_port = 44300 + vm_id
                    rdp_port = 33000 + vm_id
                    
                    if db_vm.ports_config:
                        try:
                            ports = json.loads(db_vm.ports_config)
                            for p in ports:
                                int_p = p.get("int_port")
                                ext_p = p.get("ext_port")
                                if int_p == 22:
                                    ssh_port = ext_p
                                elif int_p == 80:
                                    http_port = ext_p
                                elif int_p == 443:
                                    https_port = ext_p
                                elif int_p == 3389:
                                    rdp_port = ext_p
                        except Exception:
                            pass
            finally:
                db.close()
        except Exception:
            pass

        # Фолбэк на IP, если не удалось получить ID из БД
        if ssh_port is None:
            for ip in ips:
                if "." in ip and not ip.startswith("10.244.") and not ip.startswith("127."):
                    try:
                        last_octet = int(ip.split(".")[-1])
                        ssh_port = 22000 + last_octet
                        http_port = 28000 + last_octet
                        https_port = 44300 + last_octet
                        rdp_port = 33000 + last_octet
                        break
                    except ValueError:
                        pass

        return {
            "name": name,
            "namespace": namespace,
            "desired_state": "Running" if running_desired else "Stopped",
            "status": status,
            "import_progress": import_progress,
            "os_type": os_type,
            "cpu_cores": cpu_cores,
            "memory": mem_req,
            "disks": disks,
            "ips": ips,
            "ssh_port": ssh_port,
            "rdp_port": rdp_port,
            "http_port": http_port,
            "https_port": https_port,
            "node": node_name,
            "created_at": creation_timestamp,
            "credentials": credentials
        }

    def ensure_network_isolation(self):
        """Гарантирует, что мосты Multus не могут общаться друг с другом на L3, но разрешает локальный бриджинг"""
        try:
            import subprocess
            nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
            
            # Получаем текущие правила FORWARD
            check_cmd = "iptables -S FORWARD"
            res = subprocess.run(nsenter_prefix + [check_cmd], capture_output=True, text=True, timeout=5)
            
            if res.returncode == 0:
                # Очищаем все старые правила с br-+ для предотвращения дубликатов и наложения
                for line in res.stdout.splitlines():
                    if "br-+" in line:
                        del_rule = line.replace("-A ", "iptables -D ")
                        subprocess.run(nsenter_prefix + [del_rule], capture_output=True, timeout=5)
            
            # Добавляем правила заново
            logger.info("Настройка правил iptables для L3 изоляции мостов Multus с поддержкой локального бриджинга")
            
            # 1. Сначала добавляем запрещающее правило в начало FORWARD
            add_reject = "iptables -I FORWARD -i br-+ -o br-+ -j REJECT --reject-with icmp-port-unreachable"
            subprocess.run(nsenter_prefix + [add_reject], capture_output=True, text=True, timeout=5)
            
            # 2. Затем добавляем разрешающее правило для локального трафика внутри одного моста в самую первую позицию (сдвигая REJECT на вторую)
            add_accept = "iptables -I FORWARD -i br-+ -o br-+ -m physdev --physdev-is-bridged -j ACCEPT"
            subprocess.run(nsenter_prefix + [add_accept], capture_output=True, text=True, timeout=5)
            
            # Сохраняем правила
            subprocess.run(nsenter_prefix + ["netfilter-persistent save"], capture_output=True, text=True, timeout=5)
        except Exception as e:
            logger.error(f"Ошибка при настройке L3 изоляции сетей: {e}")

    def create_network_attachment_definition(self, name: str, namespace="default"):
        """Создает Multus NetworkAttachmentDefinition для приватной сети"""
        manifest = {
            "apiVersion": "k8s.cni.cncf.io/v1",
            "kind": "NetworkAttachmentDefinition",
            "metadata": {
                "name": name,
                "namespace": namespace
            },
            "spec": {
                "config": '{ "cniVersion": "0.3.1", "type": "bridge", "bridge": "br-' + name[:11] + '", "isGateway": true, "ipam": { "type": "host-local", "subnet": "192.168.100.0/24" } }'
            }
        }
        try:
            self.custom_api.create_namespaced_custom_object(
                group="k8s.cni.cncf.io",
                version="v1",
                namespace=namespace,
                plural="network-attachment-definitions",
                body=manifest
            )
            logger.info(f"Created NAD {name}")
            
            # Применяем L3 изоляцию сетей
            self.ensure_network_isolation()
        except ApiException as e:
            if e.status != 409: # Игнорируем если уже существует
                logger.error(f"Ошибка создания Multus Network {name}: {e}")
                raise e
            # Убедимся, что правила изоляции применены даже если NAD уже существовал
            self.ensure_network_isolation()

    def query_prometheus(self, prom_query: str, start_time: int = None, end_time: int = None, step: str = "30s"):
        """Выполняет запрос к Prometheus: сначала пытается напрямую по ClusterIP, затем через прокси API Kubernetes"""
        import urllib.request
        import urllib.parse
        import json

        try:
            # Если start_time и end_time переданы, выполняем query_range
            if start_time and end_time:
                path = f"api/v1/query_range?query={prom_query}&start={start_time}&end={end_time}&step={step}"
            else:
                path = f"api/v1/query?query={prom_query}"
                
            # Автоматический поиск сервиса Prometheus в кластере
            prom_svc_name = "prometheus-kube-prometheus-prometheus"
            prom_namespace = "prometheus"
            prom_port = 9090
            prom_cluster_ip = None

            try:
                all_svcs = self.core_api.list_service_for_all_namespaces()
                for svc in all_svcs.items:
                    s_name = svc.metadata.name.lower()
                    # Ищем сервис, содержащий prometheus в названии и имеющий порт 9090, исключая экспортеры/операторы
                    if "prometheus" in s_name and not any(x in s_name for x in ["node-exporter", "alertmanager", "operator", "agent"]):
                        for p in svc.spec.ports:
                            if p.port == 9090 or p.target_port == 9090:
                                prom_svc_name = svc.metadata.name
                                prom_namespace = svc.metadata.namespace
                                prom_port = p.port
                                prom_cluster_ip = svc.spec.cluster_ip
                                break
                        if prom_cluster_ip:
                            break
            except Exception as scan_err:
                logger.warning(f"Failed to auto-scan Prometheus services: {scan_err}")
                
            # 1. Попробуем выполнить запрос напрямую к ClusterIP сервиса Prometheus
            try:
                if not prom_cluster_ip:
                    # Если автопоиск не сработал, пробуем прочитать дефолтный сервис
                    svc = self.core_api.read_namespaced_service(
                        name=prom_svc_name,
                        namespace=prom_namespace
                    )
                    prom_cluster_ip = svc.spec.cluster_ip
                    if svc.spec.ports:
                        for p in svc.spec.ports:
                            if p.name == "http-web" or p.port == 9090:
                                prom_port = p.port
                                break
                
                # Аккуратно кодируем параметры запроса
                parts = path.split('?', 1)
                if len(parts) == 2:
                    base_path = parts[0]
                    query_params = urllib.parse.parse_qsl(parts[1])
                    encoded_params = urllib.parse.urlencode(query_params)
                    full_path = f"{base_path}?{encoded_params}"
                else:
                    full_path = path
                    
                direct_url = f"http://{prom_cluster_ip}:{prom_port}/{full_path}"
                logger.info(f"Querying Prometheus directly at {direct_url}")
                
                req = urllib.request.Request(direct_url)
                with urllib.request.urlopen(req, timeout=5) as response:
                    res_body = response.read().decode("utf-8")
                    return json.loads(res_body)
            except Exception as direct_err:
                logger.warning(f"Direct Prometheus query failed: {direct_err}. Falling back to K8s API proxy.")
                
                # 2. Резервный вариант через прокси K8s API
                path_encoded = urllib.parse.quote(path, safe="?=&")
                res = self.core_api.connect_get_namespaced_service_proxy_with_path(
                    name=f"http:{prom_svc_name}:{prom_port}" if not prom_svc_name.startswith("http:") else prom_svc_name,
                    namespace=prom_namespace,
                    path=path_encoded
                )
                if isinstance(res, str):
                    return json.loads(res)
                return res
        except Exception as e:
            logger.error(f"Error querying Prometheus: {e}")
            return None

    def create_pvc(self, name: str, size_gb: int, namespace: str = "default"):
        """Создает DataVolume в Kubernetes для автоматического создания disk.img и поддержки NFS/LVM"""
        storage_class = settings.STORAGE_CLASS
        volume_mode = "Block"
        access_mode = "ReadWriteOnce"
        # NFS не поддерживает режим Block и требует ReadWriteMany для живой миграции
        # local-path и hostpath требуют режима Filesystem, но поддерживают только ReadWriteOnce
        if "nfs" in storage_class.lower():
            volume_mode = "Filesystem"
            access_mode = "ReadWriteMany"
        elif "local" in storage_class.lower() or "hostpath" in storage_class.lower():
            volume_mode = "Filesystem"
            access_mode = "ReadWriteOnce"

        body = {
            "apiVersion": "cdi.kubevirt.io/v1beta1",
            "kind": "DataVolume",
            "metadata": {
                "name": name,
                "namespace": namespace
            },
            "spec": {
                "source": {
                    "blank": {}
                },
                "storage": {
                    "accessModes": [access_mode],
                    "storageClassName": storage_class,
                    "volumeMode": volume_mode,
                    "resources": {
                        "requests": {
                            "storage": f"{size_gb}Gi"
                        }
                    }
                }
            }
        }
        return self.custom_api.create_namespaced_custom_object(
            group="cdi.kubevirt.io",
            version="v1beta1",
            namespace=namespace,
            plural="datavolumes",
            body=body
        )

    def delete_pvc(self, name: str, namespace: str = "default"):
        """Удаляет DataVolume и соответствующий PVC из Kubernetes"""
        try:
            return self.custom_api.delete_namespaced_custom_object(
                group="cdi.kubevirt.io",
                version="v1beta1",
                namespace=namespace,
                plural="datavolumes",
                name=name
            )
        except Exception as e:
            try:
                return self.core_api.delete_namespaced_persistent_volume_claim(name, namespace)
            except Exception:
                raise e

    def add_vm_volume(self, vm_name: str, pvc_name: str, volume_name: str, namespace: str = "default"):
        """Горячее подключение (hotplug) тома PVC к виртуальной машине KubeVirt"""
        path = f"/apis/subresources.kubevirt.io/v1/namespaces/{namespace}/virtualmachines/{vm_name}/addvolume"
        headers = {}
        conf = self.api_client.configuration
        if conf.api_key:
            for k, v in conf.api_key.items():
                headers[k] = v
        headers['Content-Type'] = 'application/json'
        body = {
            "name": volume_name,
            "disk": {
                "disk": {
                    "bus": "virtio"
                }
            },
            "volumeSource": {
                "persistentVolumeClaim": {
                    "claimName": pvc_name
                }
            }
        }
        return self.api_client.call_api(
            resource_path=path,
            method="PUT",
            header_params=headers,
            body=body,
            auth_settings=["BearerToken"],
            _return_http_data_only=True
        )

    def remove_vm_volume(self, vm_name: str, volume_name: str, namespace: str = "default"):
        """Горячее отключение (hotplug) тома от виртуальной машины KubeVirt"""
        path = f"/apis/subresources.kubevirt.io/v1/namespaces/{namespace}/virtualmachines/{vm_name}/removevolume"
        headers = {}
        conf = self.api_client.configuration
        if conf.api_key:
            for k, v in conf.api_key.items():
                headers[k] = v
        headers['Content-Type'] = 'application/json'
        body = {
            "name": volume_name
        }
        return self.api_client.call_api(
            resource_path=path,
            method="PUT",
            header_params=headers,
            body=body,
            auth_settings=["BearerToken"],
            _return_http_data_only=True
        )

    def create_vm_snapshot(self, vm_name: str, snapshot_name: str, namespace: str = "default"):
        """Создает снимок (snapshot) виртуальной машины KubeVirt"""
        body = {
            "apiVersion": "snapshot.kubevirt.io/v1alpha3",
            "kind": "VirtualMachineSnapshot",
            "metadata": {
                "name": snapshot_name
            },
            "spec": {
                "source": {
                    "apiGroup": "kubevirt.io",
                    "kind": "VirtualMachine",
                    "name": vm_name
                }
            }
        }
        return self.custom_api.create_namespaced_custom_object(
            "snapshot.kubevirt.io", "v1alpha3", namespace, "virtualmachinesnapshots", body
        )

    def list_vm_snapshots(self, vm_name: str, namespace: str = "default"):
        """Возвращает список снимков для определенной виртуальной машины"""
        res = self.custom_api.list_namespaced_custom_object(
            "snapshot.kubevirt.io", "v1alpha3", namespace, "virtualmachinesnapshots"
        )
        items = res.get("items", [])
        # Фильтруем те, у которых source.name == vm_name
        filtered = []
        for item in items:
            source_name = item.get("spec", {}).get("source", {}).get("name")
            if source_name == vm_name:
                filtered.append({
                    "name": item.get("metadata", {}).get("name"),
                    "creation_time": item.get("metadata", {}).get("creationTimestamp"),
                    "phase": item.get("status", {}).get("phase", "Unknown"),
                    "ready_to_use": item.get("status", {}).get("readyToUse", False)
                })
        return filtered

    def delete_vm_snapshot(self, snapshot_name: str, namespace: str = "default"):
        """Удаляет снимок виртуальной машины"""
        return self.custom_api.delete_namespaced_custom_object(
            "snapshot.kubevirt.io", "v1alpha3", namespace, "virtualmachinesnapshots", snapshot_name
        )

    def restore_vm_snapshot(self, vm_name: str, snapshot_name: str, namespace: str = "default"):
        """Восстанавливает виртуальную машину из снимка (ВМ должна быть выключена)"""
        # Имя ретора должно быть уникальным
        import time
        restore_name = f"restore-{snapshot_name}-{int(time.time())}"
        body = {
            "apiVersion": "snapshot.kubevirt.io/v1alpha3",
            "kind": "VirtualMachineRestore",
            "metadata": {
                "name": restore_name
            },
            "spec": {
                "target": {
                    "apiGroup": "kubevirt.io",
                    "kind": "VirtualMachine",
                    "name": vm_name
                },
                "virtualMachineSnapshotName": snapshot_name
            }
        }
        return self.custom_api.create_namespaced_custom_object(
            "snapshot.kubevirt.io", "v1alpha3", namespace, "virtualmachinerestores", body
        )

    def create_private_db(self, db_name: str, engine: str, db_user: str, db_password: str, vm_name: str = None, namespace: str = "default"):
        """Создает выделенный приватный под базы данных с диском на СХД и сетевой политикой в K8s"""
        # 1. Создаем PVC под хранилище
        pvc_body = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": f"db-pvc-{db_name}"
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": settings.STORAGE_CLASS,
                "resources": {
                    "requests": {
                        "storage": "5Gi"
                    }
                }
            }
        }
        try:
            self.core_api.create_namespaced_persistent_volume_claim(namespace, pvc_body)
        except ApiException as e:
            if e.status != 409: # Игнорируем ошибку, если уже существует
                raise e

        # 2. Создаем Deployment СУБД
        port = 5432 if engine == "postgresql" else 3306
        image = "postgres:15-alpine" if engine == "postgresql" else "mariadb:10.11-jammy"
        
        env = []
        if engine == "postgresql":
            env = [
                {"name": "POSTGRES_DB", "value": db_name},
                {"name": "POSTGRES_USER", "value": db_user},
                {"name": "POSTGRES_PASSWORD", "value": db_password},
            ]
            mount_path = "/var/lib/postgresql/data"
        else:
            env = [
                {"name": "MARIADB_DATABASE", "value": db_name},
                {"name": "MARIADB_USER", "value": db_user},
                {"name": "MARIADB_PASSWORD", "value": db_password},
                {"name": "MARIADB_ROOT_PASSWORD", "value": "mariadb-root-secret-2026"},
            ]
            mount_path = "/var/lib/mysql"

        deploy_body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": f"db-deploy-{db_name}"
            },
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {
                        "app": f"db-{db_name}"
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": f"db-{db_name}"
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "db",
                                "image": image,
                                "env": env,
                                "ports": [
                                    {
                                        "containerPort": port
                                    }
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "data",
                                        "mountPath": mount_path
                                    }
                                ],
                                "resources": {
                                    "requests": {
                                        "cpu": "100m",
                                        "memory": "256Mi"
                                    },
                                    "limits": {
                                        "cpu": "500m",
                                        "memory": "512Mi"
                                    }
                                }
                            }
                        ],
                        "volumes": [
                            {
                                "name": "data",
                                "persistentVolumeClaim": {
                                    "claimName": f"db-pvc-{db_name}"
                                }
                            }
                        ]
                    }
                }
            }
        }
        apps_api = client.AppsV1Api(self.api_client)
        try:
            apps_api.create_namespaced_deployment(namespace, deploy_body)
        except ApiException as e:
            if e.status != 409:
                raise e

        # 3. Создаем Service
        svc_body = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": f"db-service-{db_name}"
            },
            "spec": {
                "selector": {
                    "app": f"db-{db_name}"
                },
                "ports": [
                    {
                        "port": port,
                        "targetPort": port
                    }
                ],
                "type": "ClusterIP"
            }
        }
        try:
            self.core_api.create_namespaced_service(namespace, svc_body)
        except ApiException as e:
            if e.status != 409:
                raise e

        # 4. Создаем NetworkPolicy для изоляции
        self.update_db_network_policy(db_name, vm_name, namespace)

    def delete_private_db(self, db_name: str, namespace: str = "default"):
        """Удаляет все ресурсы приватного пода базы данных в K8s"""
        apps_api = client.AppsV1Api(self.api_client)
        net_api = client.NetworkingV1Api(self.api_client)
        
        # 1. Удаляем NetworkPolicy
        try:
            net_api.delete_namespaced_network_policy(f"db-netpol-{db_name}", namespace)
        except Exception:
            pass
            
        # 2. Удаляем Service
        try:
            self.core_api.delete_namespaced_service(f"db-service-{db_name}", namespace)
        except Exception:
            pass
            
        # 3. Удаляем Deployment
        try:
            apps_api.delete_namespaced_deployment(f"db-deploy-{db_name}", namespace)
        except Exception:
            pass
            
        # 4. Удаляем PVC
        try:
            self.core_api.delete_namespaced_persistent_volume_claim(f"db-pvc-{db_name}", namespace)
        except Exception:
            pass

    def update_db_network_policy(self, db_name: str, vm_name: str = None, namespace: str = "default"):
        """Обновляет NetworkPolicy базы данных, разрешая доступ только определенной ВМ"""
        net_api = client.NetworkingV1Api(self.api_client)
        ingress = []
        if vm_name:
            ingress = [
                {
                    "from": [
                        {
                            "podSelector": {
                                "matchLabels": {
                                    "vm.kubevirt.io/name": vm_name
                                }
                            }
                        }
                    ]
                }
            ]
            
        body = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": f"db-netpol-{db_name}"
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {
                        "app": f"db-{db_name}"
                    }
                },
                "policyTypes": ["Ingress"],
                "ingress": ingress
            }
        }
        try:
            net_api.replace_namespaced_network_policy(f"db-netpol-{db_name}", namespace, body)
        except ApiException as e:
            if e.status == 404:
                try:
                    net_api.create_namespaced_network_policy(namespace, body)
                except ApiException as ae:
                    if ae.status != 409:
                        raise ae
            else:
                raise e

    def get_private_db_status(self, db_name: str, namespace: str = "default"):
        """Возвращает статус доступности пода СУБД"""
        apps_api = client.AppsV1Api(self.api_client)
        try:
            deploy = apps_api.read_namespaced_deployment_status(f"db-deploy-{db_name}", namespace)
            ready = deploy.status.ready_replicas
            if ready and ready > 0:
                return "Active"
            return "Pending"
        except Exception:
            return "Error"

