import logging
import os
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
        """Удалить VM и связанные диски (DataVolume / PVC)"""
        try:
            # Получаем VM, чтобы узнать имена связанных DataVolume
            vm = self.custom_api.get_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=name
            )
            
            # Удаляем саму VM
            self.custom_api.delete_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=namespace,
                plural="virtualmachines",
                name=name
            )
            
            # Удаляем диски (DataVolume), если они есть в шаблонах
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
            
            # На всякий случай удаляем связанные PVC
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
            # KubeVirt использует subresources для надежного управления питанием
            # Пример пути: /apis/subresources.kubevirt.io/v1/namespaces/default/virtualmachines/myvm/start
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
            # Находим Launcher-под для этой VM
            # Все поды виртуалок имеют лейбл kubevirt.io/domain=ИМЯ_VM
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

            # Делаем запрос к Metrics API (metrics.k8s.io)
            try:
                metrics = self.custom_api.get_namespaced_custom_object(
                    group="metrics.k8s.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="pods",
                    name=pod_name
                )
                
                # Суммируем потребление по всем контейнерам внутри пода лаунчера
                cpu_nano = 0
                mem_bytes = 0
                
                for container in metrics.get("containers", []):
                    cpu_str = container["usage"]["cpu"]
                    mem_str = container["usage"]["memory"]
                    
                    # Парсим CPU (обычно в нс, например, "123456n")
                    if cpu_str.endswith("n"):
                        cpu_nano += int(cpu_str[:-1])
                    elif cpu_str.endswith("u"):
                        cpu_nano += int(cpu_str[:-1]) * 1000
                    elif cpu_str.endswith("m"):
                        cpu_nano += int(cpu_str[:-1]) * 1000000
                    else:
                        cpu_nano += int(float(cpu_str) * 1000000000)
                        
                    # Парсим Memory (обычно в Ki, Mi, Gi)
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
                
                # Переводим CPU в милликоры (1 millicore = 10^6 nanocores)
                cpu_milli = cpu_nano / 1000000
                
                return {
                    "cpu_milli": round(cpu_milli, 2),
                    "memory_bytes": mem_bytes,
                    "memory_mb": round(mem_bytes / (1024 * 1024), 2),
                    "status": "Running"
                }
            except ApiException as e:
                # Если metrics-server еще не собрал метрики или отсутствует
                logger.warning(f"Ошибка получения raw-метрик для {pod_name}: {e}")
                return {"cpu_usage_milli": 0, "memory_bytes": 0, "status": "Running (No Metrics)"}
                
        except Exception as e:
            logger.error(f"Не удалось получить метрики для VM {name}: {e}")
            return {"cpu_usage": 0, "memory_usage": 0, "error": str(e)}

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---

    def _parse_vm_object(self, vm: dict, vmi: dict = None) -> dict:
        """Преобразует сырой манифест KubeVirt в чистый JSON-объект для фронтенда"""
        name = vm["metadata"]["name"]
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
                # KubeVirt может возвращать как внутренний Pod IP, так и внешний Bridge IP
                ip = iface.get("ipAddress")
                if ip:
                    ips.append(ip)
                # Иногда IP лежит в массиве ipAddresses
                for ip_addr in iface.get("ipAddresses", []):
                    if ip_addr not in ips:
                        ips.append(ip_addr)

        # Шаблон ОС
        os_type = vm["metadata"].get("labels", {}).get("hosting.antigravity.io/template", "unknown")

        return {
            "name": name,
            "namespace": vm["metadata"]["namespace"],
            "desired_state": "Running" if running_desired else "Stopped",
            "status": status,
            "os_type": os_type,
            "cpu_cores": cpu_cores,
            "memory": mem_req,
            "disks": disks,
            "ips": ips,
            "node": node_name,
            "created_at": creation_timestamp
        }
