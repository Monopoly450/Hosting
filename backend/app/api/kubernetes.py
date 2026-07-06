import logging
from fastapi import APIRouter, HTTPException, Depends

from kubernetes import client as k8s_sdk

from app.core.k8s_client import K8sClient

router = APIRouter()
logger = logging.getLogger("app.api.kubernetes")


def _mem_to_gb(mem: str) -> float:
    """Переводит capacity памяти ноды (например '16305672Ki') в ГБ."""
    if not mem:
        return 0.0
    try:
        if mem.endswith("Ki"):
            return round(int(mem[:-2]) / (1024 * 1024), 1)
        if mem.endswith("Mi"):
            return round(int(mem[:-2]) / 1024, 1)
        if mem.endswith("Gi"):
            return round(int(mem[:-2]), 1)
        return round(int(mem) / (1024 ** 3), 1)
    except Exception:
        return 0.0


@router.get("/overview")
def kubernetes_overview():
    """Подробная сводка по кластеру Kubernetes: версии, ноды, поды, namespaces,
    версия и feature-gates KubeVirt."""
    k8s = K8sClient()
    core = k8s.core_api

    result = {
        "k8s_version": "неизвестно",
        "kubevirt_version": "неизвестно",
        "cdi_version": "неизвестно",
        "feature_gates": [],
        "storage_class": None,
        "counts": {"nodes": 0, "pods_running": 0, "pods_total": 0, "namespaces": 0, "vms": 0},
        "nodes": [],
        "pods": [],
        "namespaces": [],
    }

    # Версия Kubernetes
    try:
        ver = k8s_sdk.VersionApi(k8s.api_client).get_code()
        result["k8s_version"] = ver.git_version
    except Exception as e:
        logger.warning(f"k8s version: {e}")

    # Ноды
    pods_by_node = {}
    try:
        all_pods = core.list_pod_for_all_namespaces(watch=False)
        pods = all_pods.items
        result["counts"]["pods_total"] = len(pods)
        for p in pods:
            phase = p.status.phase or "Unknown"
            node = p.spec.node_name or "—"
            pods_by_node[node] = pods_by_node.get(node, 0) + 1
            if phase == "Running":
                result["counts"]["pods_running"] += 1
            restarts = 0
            try:
                restarts = sum((cs.restart_count or 0) for cs in (p.status.container_statuses or []))
            except Exception:
                pass
            result["pods"].append({
                "namespace": p.metadata.namespace,
                "name": p.metadata.name,
                "phase": phase,
                "node": node,
                "restarts": restarts,
            })
    except Exception as e:
        logger.warning(f"list pods: {e}")

    try:
        nodes = core.list_node().items
        result["counts"]["nodes"] = len(nodes)
        for n in nodes:
            labels = n.metadata.labels or {}
            roles = [k.split("/")[-1] for k in labels if k.startswith("node-role.kubernetes.io/")]
            if not roles:
                roles = ["master"] if labels.get("node-role.kubernetes.io/master") is not None else ["worker"]
            ready = "NotReady"
            for cond in (n.status.conditions or []):
                if cond.type == "Ready":
                    ready = "Ready" if cond.status == "True" else "NotReady"
            internal_ip = next((a.address for a in (n.status.addresses or []) if a.type == "InternalIP"), "—")
            cap = n.status.capacity or {}
            info = n.status.node_info
            result["nodes"].append({
                "name": n.metadata.name,
                "ready": ready,
                "roles": roles or ["worker"],
                "version": info.kubelet_version if info else "—",
                "os_image": info.os_image if info else "—",
                "kernel": info.kernel_version if info else "—",
                "container_runtime": info.container_runtime_version if info else "—",
                "internal_ip": internal_ip,
                "cpu": cap.get("cpu", "—"),
                "memory_gb": _mem_to_gb(cap.get("memory", "")),
                "pods": pods_by_node.get(n.metadata.name, 0),
                "schedulable": not (n.spec.unschedulable or False),
            })
    except Exception as e:
        logger.warning(f"list nodes: {e}")

    # Namespaces
    try:
        ns = core.list_namespace().items
        result["namespaces"] = [x.metadata.name for x in ns]
        result["counts"]["namespaces"] = len(ns)
    except Exception as e:
        logger.warning(f"list namespaces: {e}")

    # KubeVirt: версия + feature gates
    try:
        kv = k8s.custom_api.get_cluster_custom_object("kubevirt.io", "v1", "kubevirt", "kubevirt")
        result["kubevirt_version"] = (kv.get("status", {}) or {}).get("observedKubeVirtVersion", "неизвестно")
        dev = (((kv.get("spec", {}) or {}).get("configuration", {}) or {}).get("developerConfiguration", {}) or {})
        result["feature_gates"] = dev.get("featureGates", []) or []
    except Exception as e:
        logger.warning(f"kubevirt info: {e}")

    # CDI version
    try:
        cdi = k8s.custom_api.get_cluster_custom_object("cdi.kubevirt.io", "v1beta1", "cdis", "cdi")
        result["cdi_version"] = (cdi.get("status", {}) or {}).get("observedVersion", "неизвестно")
    except Exception:
        pass

    # Кол-во ВМ
    try:
        result["counts"]["vms"] = len(k8s.list_vms())
    except Exception:
        pass

    import os
    result["storage_class"] = os.getenv("STORAGE_CLASS", "local-path")

    return result


@router.get("/join-token")
def get_join_token():
    """Возвращает команду присоединения worker-ноды к кластеру (K3s join token
    читается на хосте). Только для админа."""
    import subprocess
    nsenter = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "sh", "-c"]
    token = None
    try:
        res = subprocess.run(nsenter + ["cat /var/lib/rancher/k3s/server/node-token"],
                             capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            token = res.stdout.strip()
    except Exception as e:
        logger.warning(f"join token: {e}")
    master_ip = None
    try:
        k8s = K8sClient()
        nodes = k8s.core_api.list_node().items
        if nodes:
            master_ip = next((a.address for a in (nodes[0].status.addresses or []) if a.type == "InternalIP"), None)
    except Exception:
        pass
    return {
        "available": token is not None,
        "token": token,
        "master_ip": master_ip,
        "join_command": (
            f"curl -sfL https://get.k3s.io | K3S_URL=https://{master_ip or '<MASTER_IP>'}:6443 "
            f"K3S_TOKEN={token or '<TOKEN>'} sh -"
        ),
    }
