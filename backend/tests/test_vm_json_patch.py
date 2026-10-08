"""Регрессия запуска ВМ с настоящим kubernetes==30.1.0, без сети."""
import copy
import json

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException
from urllib3.response import HTTPResponse

from app.core.k8s_client import K8sClient


@pytest.fixture
def vm_transport(monkeypatch):
    config = client.Configuration()
    config.host = "https://kubernetes.invalid"
    config.api_key["authorization"] = "test-token"
    config.api_key_prefix["authorization"] = "Bearer"
    api = client.ApiClient(config)
    k8s = K8sClient.__new__(K8sClient)
    k8s.api_client = api
    k8s.custom_api = client.CustomObjectsApi(api)
    vm = {
        "metadata": {
            "name": "vm1", "namespace": "tenant",
            "resourceVersion": "1", "annotations": {},
        },
        "spec": {"running": False},
    }
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, copy.deepcopy(kwargs)))
        if method == "PATCH":
            assert kwargs["headers"]["Content-Type"] == "application/json-patch+json"
            assert kwargs["headers"]["authorization"] == "Bearer test-token"
            for operation in kwargs["body"]:
                parts = [part.replace("~1", "/").replace("~0", "~")
                         for part in operation["path"].split("/")[1:]]
                parent = vm
                for part in parts[:-1]:
                    parent = parent[part]
                key = parts[-1]
                if operation["op"] == "test":
                    if parent.get(key) != operation["value"]:
                        raise ApiException(status=409, reason="state changed")
                elif operation["op"] == "add":
                    parent[key] = operation["value"]
                elif operation["op"] == "remove":
                    del parent[key]
                else:
                    pytest.fail(f"Unexpected operation: {operation}")
            vm["metadata"]["resourceVersion"] = str(
                int(vm["metadata"]["resourceVersion"]) + 1
            )
        response = vm if url.endswith("/vm1") else {"items": []}
        return HTTPResponse(
            body=json.dumps(response).encode(), status=200,
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(api, "request", request)
    yield k8s, vm, requests
    api.close()


@pytest.mark.parametrize("action", ["start", "restart"])
@pytest.mark.parametrize("annotations", [{}, None])
def test_guarded_power_action_works_with_real_sdk(vm_transport, action, annotations):
    k8s, vm, requests = vm_transport
    vm["metadata"]["annotations"] = annotations

    result = k8s.guarded_power_action(action, "vm1", "tenant")

    assert result == {"status": "success", "action": action, "name": "vm1"}
    writes = [r for r in requests if r[0] != "GET"]
    assert [r[0] for r in writes] == ["PATCH", "PUT", "PATCH"]
    assert writes[1][1].endswith(f"/namespaces/tenant/virtualmachines/vm1/{action}")
    assert writes[0][2]["body"][0] == {
        "op": "test", "path": "/metadata/resourceVersion", "value": "1",
    }
    assert writes[2][2]["body"][0]["value"] == "2"
    assert K8sClient.VM_ACTION_GUARD not in vm["metadata"]["annotations"]


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_backup_locks_acquire_and_clear_with_real_sdk(vm_transport, operation):
    k8s, vm, requests = vm_transport
    if operation == "backup":
        k8s.acquire_backup_operation(copy.deepcopy(vm), "backup1", True, "disk1", "tenant")
        assert vm["metadata"]["annotations"][k8s.BACKUP_OPERATION] == "backup1"
        k8s.clear_backup_operation("vm1", "backup1", "tenant")
    else:
        k8s.acquire_backup_restore_operation(
            copy.deepcopy(vm), "restore1", "backup1", "disk2", True, "tenant", "disk1",
        )
        assert vm["metadata"]["annotations"][k8s.BACKUP_RESTORE_OPERATION] == "restore1"
        k8s.clear_backup_restore_operation("vm1", "restore1", "tenant")

    assert vm["metadata"]["annotations"] == {}
    patches = [r for r in requests if r[0] == "PATCH"]
    assert len(patches) == 2
    assert all(r[1].endswith("/namespaces/tenant/virtualmachines/vm1") for r in patches)


@pytest.mark.parametrize("status", [409, 422])
@pytest.mark.parametrize("operation", ["start", "backup", "restore"])
def test_lock_conflicts_remain_user_errors(vm_transport, monkeypatch, status, operation):
    k8s, vm, requests = vm_transport
    original_request = k8s.api_client.request

    def conflict(method, url, **kwargs):
        if method == "PATCH":
            raise ApiException(status=status, reason="state changed")
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(k8s.api_client, "request", conflict)
    with pytest.raises(ValueError, match="Состояние ВМ изменилось"):
        if operation == "start":
            k8s.guarded_power_action("start", "vm1", "tenant")
        elif operation == "backup":
            k8s.acquire_backup_operation(copy.deepcopy(vm), "backup1", True, "disk1", "tenant")
        else:
            k8s.acquire_backup_restore_operation(
                copy.deepcopy(vm), "restore1", "backup1", "disk2", True, "tenant",
            )
    assert not any(r[0] == "PUT" for r in requests)


def test_guard_cleanup_keeps_another_operations_lock(vm_transport):
    k8s, vm, requests = vm_transport
    vm["metadata"]["annotations"][k8s.VM_ACTION_GUARD] = "start:other-token"

    k8s.clear_vm_action_guard("vm1", "start:old-token", "tenant")

    assert vm["metadata"]["annotations"][k8s.VM_ACTION_GUARD] == "start:other-token"
    assert not any(r[0] == "PATCH" for r in requests)


def test_s3_lock_is_durable_and_blocks_power_actions(vm_transport):
    k8s, vm, requests = vm_transport
    k8s.acquire_s3_operation("vm1", "s3-backup-1", "tenant")
    assert vm["metadata"]["annotations"][k8s.S3_OPERATION] == "s3-backup-1"
    with pytest.raises(ValueError, match="S3"):
        k8s.guarded_power_action("start", "vm1", "tenant")
    k8s.acquire_s3_operation("vm1", "s3-backup-1", "tenant")
    assert len([r for r in requests if r[0] == "PATCH"]) == 1
    k8s.clear_s3_operation("vm1", "another-operation", "tenant")
    assert vm["metadata"]["annotations"][k8s.S3_OPERATION] == "s3-backup-1"
    k8s.clear_s3_operation("vm1", "s3-backup-1", "tenant")
    assert k8s.S3_OPERATION not in vm["metadata"]["annotations"]


def test_s3_can_replace_an_expired_power_guard(vm_transport):
    k8s, vm, _requests = vm_transport
    vm["metadata"]["annotations"][k8s.VM_ACTION_GUARD] = "start:token:0"
    k8s.acquire_s3_operation("vm1", "s3-backup-1", "tenant")
    assert vm["metadata"]["annotations"][k8s.S3_OPERATION] == "s3-backup-1"
