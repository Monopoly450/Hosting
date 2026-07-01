import logging
from kubernetes.client.rest import ApiException

logger = logging.getLogger("app.k8s_clusters")

def add_cluster_methods_to_k8s_client(K8sClient):
    def list_clusters(self):
        try:
            namespaces = self.core_api.list_namespace(label_selector="hosting.antigravity.io/cluster=true")
            clusters = []
            for ns in namespaces.items:
                cluster_name = ns.metadata.labels.get("hosting.antigravity.io/cluster-name", ns.metadata.name)
                # Получаем виртуалки в этом неймспейсе
                vms = self.list_vms(namespace=ns.metadata.name)
                
                # Получаем квоту
                quota = None
                try:
                    quota_obj = self.core_api.read_namespaced_resource_quota(name="cluster-quota", namespace=ns.metadata.name)
                    quota = {
                        "hard": quota_obj.spec.hard,
                        "used": quota_obj.status.used
                    }
                except ApiException:
                    pass
                    
                clusters.append({
                    "id": ns.metadata.name,
                    "name": cluster_name,
                    "vms": vms,
                    "quota": quota,
                    "created_at": ns.metadata.creation_timestamp
                })
            return clusters
        except ApiException as e:
            logger.error(f"Ошибка получения кластеров: {e}")
            raise e

    def create_cluster_env(self, cluster_id: str, cluster_name: str, total_cpu: int, total_mem: int, total_disk: int):
        from kubernetes import client
        
        # 1. Создаем Namespace
        ns_body = client.V1Namespace(
            metadata=client.V1ObjectMeta(
                name=cluster_id,
                labels={
                    "hosting.antigravity.io/cluster": "true",
                    "hosting.antigravity.io/cluster-name": cluster_name
                }
            )
        )
        try:
            self.core_api.create_namespace(body=ns_body)
        except ApiException as e:
            if e.status != 409: # 409 Conflict means it already exists
                raise e
                
        # 2. Создаем NetworkPolicy (запрет входящего трафика извне)
        netpol_body = client.V1NetworkPolicy(
            metadata=client.V1ObjectMeta(name="isolate-cluster", namespace=cluster_id),
            spec=client.V1NetworkPolicySpec(
                pod_selector=client.V1LabelSelector(match_labels={}), # Все поды
                policy_types=["Ingress"],
                ingress=[
                    client.V1NetworkPolicyIngressRule(
                        _from=[
                            client.V1NetworkPolicyPeer(
                                pod_selector=client.V1LabelSelector(match_labels={}) # Разрешаем внутри того же неймспейса
                            )
                        ]
                    )
                ]
            )
        )
        try:
            client.NetworkingV1Api(self.api_client).create_namespaced_network_policy(namespace=cluster_id, body=netpol_body)
        except ApiException as e:
            if e.status != 409:
                pass # Игнорируем конфликты
                
        # 3. Создаем ResourceQuota (Опционально)
        quota_body = client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(name="cluster-quota", namespace=cluster_id),
            spec=client.V1ResourceQuotaSpec(
                hard={
                    "requests.cpu": str(total_cpu),
                    "requests.memory": f"{total_mem}Gi",
                    "requests.storage": f"{total_disk}Gi"
                }
            )
        )
        try:
            self.core_api.create_namespaced_resource_quota(namespace=cluster_id, body=quota_body)
        except ApiException as e:
            if e.status != 409:
                pass

    def delete_cluster_env(self, cluster_id: str):
        try:
            self.core_api.delete_namespace(name=cluster_id)
        except ApiException as e:
            if e.status != 404:
                raise e

    K8sClient.list_clusters = list_clusters
    K8sClient.create_cluster_env = create_cluster_env
    K8sClient.delete_cluster_env = delete_cluster_env

