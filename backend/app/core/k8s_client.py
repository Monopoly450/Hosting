import logging
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
                        self.core_api.delete_namespaced_volume_claim(pvc_name, namespace)
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

    def create_credentials_secret(self, name: str, password: str, namespace="default"):
        """Создает Secret с паролем root пользователя для виртуалки"""
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
                    "username": "root",
                    "password": password
                }
            )
            self.core_api.create_namespaced_secret(namespace, secret)
            logger.info(f"Создан секрет {secret_name} с учетными данными для ВМ {name}")
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
                        "storageClassName": "local-path",
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
                self.core_api.delete_namespaced_volume_claim(backup_name, namespace)
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
                        "storageClassName": "local-path",
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
            disks.append({
                "name": dv["metadata"]["name"],
                "size": size,
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
            except Exception:
                pass

        # Получаем данные из запущенного инстанса (VMI)
        status = "Stopped"
        ips = []
        node_name = ""
        creation_timestamp = vm["metadata"].get("creationTimestamp")
        
        if vmi:
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
        else:
            if import_phase:
                status = "Importing"
            elif running_desired:
                status = "Starting"
            else:
                status = "Stopped"

        # Шаблон ОС
        os_type = vm["metadata"].get("labels", {}).get("hosting.antigravity.io/template", "unknown")

        # Получаем учетные данные (логин root + авто-пароль из секретов K8s)
        credentials = {"username": "root", "password": "N/A"}
        try:
            secret = self.core_api.read_namespaced_secret(f"{name}-credentials", namespace)
            pw = base64.b64decode(secret.data["password"]).decode("utf-8")
            credentials["password"] = pw
        except Exception:
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
            "node": node_name,
            "created_at": creation_timestamp,
            "credentials": credentials
        }
