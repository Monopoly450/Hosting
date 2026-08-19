import os

import pytest
from fastapi import HTTPException
from kubernetes.client.rest import ApiException

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis",
)

from app.api import snapshots as snapshot_api
from app.core.k8s_client import K8sClient


def _pvc(size="20Gi"):
    resources = type("Resources", (), {"requests": {"storage": size}})()
    spec = type("Spec", (), {
        "resources": resources,
        "access_modes": ["ReadWriteOnce"],
        "volume_mode": "Block",
    })()
    return type("PVC", (), {"spec": spec})()


def _vm(running=True):
    return {
        "spec": {
            "running": running,
            "template": {"spec": {
                "domain": {"devices": {"disks": [
                    {"name": "root", "disk": {"bus": "virtio"}},
                ]}},
                "volumes": [
                    {"name": "root", "dataVolume": {"name": "vm1-disk"}},
                ],
            }},
            "dataVolumeTemplates": [{
                "metadata": {"name": "vm1-disk"},
                "spec": {
                    "source": {"http": {"url": "https://example.invalid/os.img"}},
                    "storage": {"resources": {"requests": {"storage": "20Gi"}}},
                },
            }],
        }
    }


class RestoreCustomApi:
    def __init__(self):
        self.vm = _vm()
        self.patches = []
        self.deleted = []
        self.created = []

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        if plural == "datavolumes" and name == "vm1-backup-1":
            return {
                "metadata": {
                    "name": name,
                    "labels": {"hosting.antigravity.io/backup-source": "vm1"},
                },
                "status": {"phase": "Succeeded"},
            }
        if plural == "virtualmachines" and name == "vm1":
            return self.vm
        raise ApiException(status=404)

    def patch_namespaced_custom_object(self, group, version, namespace, plural, name, body):
        self.patches.append((plural, name, body))
        return body

    def delete_namespaced_custom_object(self, group, version, namespace, plural, name):
        self.deleted.append((plural, name))

    def create_namespaced_custom_object(self, group, version, namespace, plural, body):
        self.created.append((plural, body))
        return body


class RestoreCoreApi:
    def __init__(self):
        self.deleted = []

    def read_namespaced_persistent_volume_claim(self, name, namespace):
        if name == "vm1-backup-1":
            return _pvc()
        raise ApiException(status=404)

    def delete_namespaced_persistent_volume_claim(self, name, namespace):
        self.deleted.append(name)


def test_backup_restore_replaces_datavolume_and_restores_desired_power_state():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreCustomApi()
    client.core_api = RestoreCoreApi()
    calls = []
    client.stop_vm = lambda name, namespace="default": calls.append(("stop", name))
    client.start_vm = lambda name, namespace="default": calls.append(("start", name))
    client.wait_for_vm_stopped = lambda name, namespace="default": True

    result = client.restore_vm_backup("vm1", "vm1-backup-1")

    assert ("datavolumes", "vm1-disk") in client.custom_api.deleted
    restored = client.custom_api.created[0][1]
    assert restored["metadata"]["name"] == "vm1-disk"
    assert restored["spec"]["source"]["pvc"]["name"] == "vm1-backup-1"
    assert calls == [("stop", "vm1"), ("start", "vm1")]
    assert result["will_restart"] is True
    # Первый patch убирает старый шаблон, второй возвращает его с backup-source.
    assert client.custom_api.patches[0][2]["spec"]["dataVolumeTemplates"] == []
    replacement = client.custom_api.patches[-1][2]["spec"]["dataVolumeTemplates"][0]
    assert replacement["spec"]["source"]["pvc"]["name"] == "vm1-backup-1"


def test_backup_restore_refuses_foreign_or_incomplete_copy_before_stopping_vm():
    client = K8sClient.__new__(K8sClient)

    class Foreign:
        def get_namespaced_custom_object(self, *args):
            return {
                "metadata": {"labels": {"hosting.antigravity.io/backup-source": "vm2"}},
                "status": {"phase": "Succeeded"},
            }

    client.custom_api = Foreign()
    with pytest.raises(ValueError, match="не принадлежит"):
        client.restore_vm_backup("vm1", "vm2-backup-1")


def test_backup_restore_puts_template_back_if_dv_creation_fails():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreCustomApi()
    client.core_api = RestoreCoreApi()
    client.stop_vm = lambda *_args, **_kwargs: None
    client.start_vm = lambda *_args, **_kwargs: None
    client.wait_for_vm_stopped = lambda *_args, **_kwargs: True

    def fail_create(*_args, **_kwargs):
        raise ApiException(status=500, reason="CDI unavailable")

    client.custom_api.create_namespaced_custom_object = fail_create
    with pytest.raises(ApiException):
        client.restore_vm_backup("vm1", "vm1-backup-1")

    # Первый patch снимает шаблон, а аварийный возвращает его уже
    # с источником-копией, а не со старым cloud-image.
    replacement = client.custom_api.patches[-1][2]["spec"]["dataVolumeTemplates"][0]
    assert replacement["spec"]["source"]["pvc"]["name"] == "vm1-backup-1"


class SnapshotClient:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.deleted = []

    def list_vm_snapshots(self, vm_name):
        return self.snapshots

    def delete_vm_snapshot(self, name):
        self.deleted.append(name)


def test_snapshot_delete_cannot_escape_vm_scope(monkeypatch):
    monkeypatch.setattr(snapshot_api, "check_vm_ownership", lambda *args, **kwargs: None)
    client = SnapshotClient([])
    with pytest.raises(HTTPException) as exc:
        snapshot_api.delete_snapshot("vm1", "snap-vm2-x", client, object())
    assert exc.value.status_code == 404
    assert client.deleted == []


def test_snapshot_restore_refuses_pending_snapshot_before_stopping_vm(monkeypatch):
    monkeypatch.setattr(snapshot_api, "check_vm_ownership", lambda *args, **kwargs: None)
    client = SnapshotClient([{
        "name": "snap-vm1-x",
        "phase": "InProgress",
        "ready_to_use": False,
        "has_disk": True,
    }])
    with pytest.raises(HTTPException) as exc:
        snapshot_api.restore_snapshot("vm1", "snap-vm1-x", client, object())
    assert exc.value.status_code == 409
