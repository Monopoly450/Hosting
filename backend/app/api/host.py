from fastapi import APIRouter, HTTPException, Depends
from app.core.k8s_client import K8sClient
from kubernetes.client.rest import ApiException

router = APIRouter()

def get_k8s_client():
    return K8sClient()

@router.get("/metrics")
def get_host_metrics(client: K8sClient = Depends(get_k8s_client)):
    """Возвращает общую емкость сервера и текущую нагрузку (CPU, RAM) из K8s Node API"""
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
            
        except ApiException as e:
            # Если метрики временно недоступны
            pass
            
        return {
            "node_name": node_name,
            "cpu": {
                "total_cores": cpu_capacity,
                "usage_cores": round(cpu_usage_milli / 1000, 2),
                "usage_percent": round((cpu_usage_milli / 1000) / cpu_capacity * 100, 1) if cpu_capacity else 0
            },
            "memory": {
                "total_gb": round(mem_capacity_bytes / (1024 * 1024 * 1024), 2),
                "allocatable_gb": round(mem_allocatable_bytes / (1024 * 1024 * 1024), 2),
                "usage_gb": round(mem_usage_bytes / (1024 * 1024 * 1024), 2),
                "usage_percent": round(mem_usage_bytes / mem_capacity_bytes * 100, 1) if mem_capacity_bytes else 0
            },
            "os_info": node.status.node_info.os_image,
            "kernel_version": node.status.node_info.kernel_version,
            "kubelet_version": node.status.node_info.kubelet_version
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
