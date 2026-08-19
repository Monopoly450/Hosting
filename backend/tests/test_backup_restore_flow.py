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
from app.api import vms as vm_api
from app.core.k8s_client import K8sClient
from app.services.backup_lifecycle import restart_vms_after_finished_backups
from app.services.snapshot_lifecycle import (
    restart_vms_after_finished_snapshot_restores,
)


def _pvc(size="20Gi"):
    resources = type("Resources", (), {"requests": {"storage": size}})()
    spec = type("Spec", (), {
        "resources": resources,
        "access_modes": ["ReadWriteOnce"],
        "volume_mode": "Block",
        "storage_class_name": "openebs-lvm",
    })()
    return type("PVC", (), {"spec": spec})()


def _vm(running=True, annotations=None):
    return {
        "metadata": {
            "name": "vm1",
            "namespace": "default",
            "resourceVersion": "1",
            "annotations": annotations or {},
        },
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

    def list_namespaced_custom_object(self, *args, **kwargs):
        return {"items": []}

    def patch_namespaced_custom_object(
        self, group, version, namespace, plural, name, body, **kwargs,
    ):
        self.patches.append((plural, name, body, kwargs))
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


class BackupLifecycleApi:
    def __init__(self):
        self.patches = []
        self.label_selectors = []

    def list_namespaced_custom_object(
        self, group, version, namespace, plural, label_selector=None,
    ):
        self.label_selectors.append(label_selector)
        return {"items": [
            {
                "metadata": {
                    "name": "backup-ok",
                    "labels": {"hosting.antigravity.io/backup-source": "vm-ok"},
                    "annotations": {K8sClient.RESTART_AFTER_BACKUP: "true"},
                },
                "status": {"phase": "Succeeded"},
            },
            {
                "metadata": {
                    "name": "backup-failed",
                    "labels": {"hosting.antigravity.io/backup-source": "vm-failed"},
                    "annotations": {K8sClient.RESTART_AFTER_BACKUP: "true"},
                },
                "status": {"phase": "Failed"},
            },
            {
                "metadata": {
                    "name": "backup-busy",
                    "labels": {"hosting.antigravity.io/backup-source": "vm-busy"},
                    "annotations": {K8sClient.RESTART_AFTER_BACKUP: "true"},
                },
                "status": {"phase": "CloneInProgress"},
            },
            {
                "metadata": {
                    "name": "backup-manual",
                    "labels": {"hosting.antigravity.io/backup-source": "vm-manual"},
                },
                "status": {"phase": "Succeeded"},
            },
        ]}

    def patch_namespaced_custom_object(
        self, group, version, namespace, plural, name, body,
    ):
        self.patches.append((plural, name, body))
        return body


class LifecycleClient:
    def __init__(self, items, fail_start=(), fail_clear=(), running=()):
        self.items = items
        self.fail_start = set(fail_start)
        self.fail_clear = set(fail_clear)
        self.started = []
        self.cleared = []
        self.cleared_operations = []
        self.running = set(running)
        self.waited = []
        self.cancelled = []

    def backups_awaiting_start(self):
        return self.items

    def start_vm(self, name):
        self.started.append(name)
        if name in self.fail_start:
            raise RuntimeError("start failed")
        self.running.add(name)

    def get_vm(self, name):
        return {"status": "Running" if name in self.running else "Stopped"}

    def clear_restart_after_backup(self, name):
        self.cleared.append(name)
        if name in self.fail_clear:
            raise RuntimeError("patch failed")

    def clear_backup_operation(self, vm_name, backup_name):
        self.cleared_operations.append((vm_name, backup_name))

    def wait_for_pvc_unused(self, pvc_name):
        self.waited.append(pvc_name)
        return True

    def cancel_backup_datavolume(self, backup_name):
        self.cancelled.append(backup_name)


class RecordingLogger:
    def info(self, *_args):
        pass

    def warning(self, *_args):
        pass

    def error(self, *_args):
        pass


class SnapshotLifecycleClient:
    def __init__(self):
        self.started = []
        self.cleared = []

    def restores_awaiting_start(self):
        return [
            {"restore": "restore-gone", "vm": "vm-gone", "failed": False},
            {"restore": "restore-ok", "vm": "vm-ok", "failed": False},
        ]

    def active_backup_operation(self, vm_name):
        if vm_name == "vm-gone":
            raise ApiException(status=404)
        return None

    def active_backup_restore_operation(self, _vm_name):
        return None

    def get_vm(self, _vm_name):
        return {"status": "Stopped", "desired_state": "Stopped"}

    def start_vm(self, vm_name):
        self.started.append(vm_name)

    def clear_restart_after_restore(self, restore_name):
        self.cleared.append(restore_name)


def test_deleted_snapshot_target_does_not_starve_later_restarts():
    client = SnapshotLifecycleClient()

    completed = restart_vms_after_finished_snapshot_restores(
        client, RecordingLogger()
    )

    assert completed == 2
    assert client.started == ["vm-ok"]
    assert client.cleared == ["restore-gone", "restore-ok"]


class BackupDeleteClient:
    def __init__(self, annotation="true", phase="CloneInProgress"):
        self.annotation = annotation
        self.phase = phase
        self.deleted = []
        self.cancelled = []

    def get_vm_backup(self, vm_name, backup_name):
        return {
            "metadata": {
                "name": backup_name,
                "labels": {"hosting.antigravity.io/backup-source": vm_name},
                "annotations": (
                    {K8sClient.RESTART_AFTER_BACKUP: self.annotation}
                    if self.annotation is not None else {}
                ),
            },
            "status": {"phase": self.phase},
        }

    def delete_vm_backup(self, backup_name, vm_name=None):
        self.deleted.append((vm_name, backup_name))
        return {"status": "deleted"}

    def active_backup_operation(self, vm_name):
        return "backup-1" if self.annotation == "true" else None

    def cancel_vm_backup(self, vm_name, backup_name):
        self.cancelled.append((vm_name, backup_name))
        return {"status": "cancelled", "backup_name": backup_name}


def test_only_terminal_offline_backups_are_selected_for_vm_restart():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = BackupLifecycleApi()

    ready = client.backups_awaiting_start()

    assert ready == [
        {
            "backup": "backup-ok", "vm": "vm-ok", "phase": "Succeeded",
            "backup_exists": True, "cancel_backup": False,
            "source_pvc": None, "restart_vm": True,
        },
        {
            "backup": "backup-failed", "vm": "vm-failed", "phase": "Failed",
            "backup_exists": True, "cancel_backup": False,
            "source_pvc": None, "restart_vm": True,
        },
    ]
    assert client.custom_api.label_selectors[0] == \
        "hosting.antigravity.io/backup-source"


def test_restart_mark_is_cleared_with_a_merge_patch():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = BackupLifecycleApi()

    client.clear_restart_after_backup("backup-ok")

    plural, name, body = client.custom_api.patches[-1]
    assert (plural, name) == ("datavolumes", "backup-ok")
    assert body["metadata"]["annotations"][K8sClient.RESTART_AFTER_BACKUP] is None


def test_offline_backup_tick_restarts_vm_for_success_and_failure():
    items = [
        {"backup": "backup-ok", "vm": "vm-ok", "phase": "Succeeded"},
        {"backup": "backup-failed", "vm": "vm-failed", "phase": "Failed"},
    ]
    client = LifecycleClient(items)

    completed = restart_vms_after_finished_backups(client, RecordingLogger())

    assert completed == 2
    assert client.started == ["vm-ok", "vm-failed"]
    assert client.cleared == ["backup-ok", "backup-failed"]
    assert client.cleared_operations == [
        ("vm-ok", "backup-ok"), ("vm-failed", "backup-failed")
    ]


def test_offline_backup_tick_keeps_restart_mark_when_start_fails():
    client = LifecycleClient(
        [{"backup": "backup-ok", "vm": "vm-ok", "phase": "Succeeded"}],
        fail_start={"vm-ok"},
    )

    assert restart_vms_after_finished_backups(client, RecordingLogger()) == 0
    assert client.started == ["vm-ok"]
    assert client.cleared == []


def test_offline_backup_tick_retries_annotation_after_patch_failure():
    client = LifecycleClient(
        [{"backup": "backup-ok", "vm": "vm-ok", "phase": "Succeeded"}],
        fail_clear={"backup-ok"},
    )

    assert restart_vms_after_finished_backups(client, RecordingLogger()) == 0
    assert client.started == ["vm-ok"]
    assert client.cleared == ["backup-ok"]
    assert client.cleared_operations == []


def test_offline_backup_tick_does_not_start_an_already_running_vm_again():
    client = LifecycleClient(
        [{"backup": "backup-ok", "vm": "vm-ok", "phase": "Succeeded"}],
        running={"vm-ok"},
    )

    assert restart_vms_after_finished_backups(client, RecordingLogger()) == 1
    assert client.started == []
    assert client.cleared == ["backup-ok"]
    assert client.cleared_operations == [("vm-ok", "backup-ok")]


@pytest.mark.parametrize("phase", ["CloneInProgress", "Succeeded", "Failed"])
def test_delete_pending_offline_backup_cancels_clone_and_returns_vm(monkeypatch, phase):
    monkeypatch.setattr(vm_api, "check_vm_ownership", lambda *_args, **_kwargs: None)
    client = BackupDeleteClient(phase=phase)

    result = vm_api.delete_backup("vm1", "backup-1", client, object())

    assert result == {"status": "cancelled", "backup_name": "backup-1"}
    assert client.cancelled == [("vm1", "backup-1")]
    assert client.deleted == []


def test_backup_can_be_deleted_after_worker_clears_restart_mark(monkeypatch):
    monkeypatch.setattr(vm_api, "check_vm_ownership", lambda *_args, **_kwargs: None)
    client = BackupDeleteClient(annotation=None, phase="Succeeded")

    result = vm_api.delete_backup("vm1", "backup-1", client, object())

    assert result == {"status": "deleted"}
    assert client.deleted == [("vm1", "backup-1")]


class BackupCreateCustomApi:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.created = []
        self.patched = []

    def list_namespaced_custom_object(self, *args, **kwargs):
        return {"items": self.existing}

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        if plural == "virtualmachines":
            return _vm(running=True)
        raise ApiException(status=404)

    def create_namespaced_custom_object(self, **kwargs):
        self.created.append(kwargs["body"])
        return kwargs["body"]

    def patch_namespaced_custom_object(
        self, group, version, namespace, plural, name, body, **kwargs,
    ):
        self.patched.append((plural, name, body, kwargs))
        return body


class BackupCreateCoreApi:
    def read_namespaced_persistent_volume_claim(self, name, namespace):
        assert name == "vm1-disk"
        return _pvc()


def _backup_create_client(existing=()):
    client = K8sClient.__new__(K8sClient)
    client.custom_api = BackupCreateCustomApi(existing)
    client.core_api = BackupCreateCoreApi()
    calls = []
    client.stop_vm = lambda name, namespace="default": calls.append(("stop", name))
    client.start_vm = lambda name, namespace="default": calls.append(("start", name))
    client.wait_for_vm_stopped = lambda name, namespace="default": True
    return client, calls


def test_running_vm_backup_is_offline_immediate_and_marked_for_restart():
    client, calls = _backup_create_client()

    result = client.create_vm_backup("vm1")

    assert calls == [("stop", "vm1")]
    assert result["will_restart"] is True
    body = client.custom_api.created[0]
    annotations = body["metadata"]["annotations"]
    assert annotations["cdi.kubevirt.io/storage.bind.immediate.requested"] == "true"
    assert annotations[K8sClient.RESTART_AFTER_BACKUP] == "true"
    assert body["spec"]["storage"]["volumeMode"] == "Block"
    vm_patch = client.custom_api.patched[0]
    assert vm_patch[0:2] == ("virtualmachines", "vm1")
    assert any(
        operation.get("value") == result["backup_name"]
        and operation.get("path", "").endswith("offline-backup")
        for operation in vm_patch[2]
    )
    assert vm_patch[3]["_content_type"] == "application/json-patch+json"


def test_second_backup_is_refused_before_the_vm_is_stopped():
    existing = [{
        "metadata": {
            "name": "vm1-backup-old",
            "annotations": {K8sClient.RESTART_AFTER_BACKUP: "true"},
        },
        "status": {"phase": "Succeeded"},
    }]
    client, calls = _backup_create_client(existing)

    with pytest.raises(ValueError, match="ещё не завершён"):
        client.create_vm_backup("vm1")

    assert calls == []
    assert client.custom_api.created == []


def test_backup_restore_stages_new_datavolume_before_touching_current_disk():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreCustomApi()
    client.core_api = RestoreCoreApi()
    calls = []
    client.stop_vm = lambda name, namespace="default": calls.append(("stop", name))
    client.start_vm = lambda name, namespace="default": calls.append(("start", name))
    client.wait_for_vm_stopped = lambda name, namespace="default": True

    result = client.restore_vm_backup("vm1", "vm1-backup-1")

    assert ("datavolumes", "vm1-disk") not in client.custom_api.deleted
    restored = client.custom_api.created[0][1]
    assert restored["metadata"]["name"] == result["operation"]
    assert restored["spec"]["source"]["pvc"]["name"] == "vm1-backup-1"
    assert calls == []
    assert result["will_restart"] is True
    assert restored["metadata"]["labels"]["hosting.antigravity.io/restore-old-pvc"] == "vm1-disk"


def test_backup_restore_refuses_foreign_or_incomplete_copy_before_stopping_vm():
    client = K8sClient.__new__(K8sClient)

    class Foreign:
        def get_namespaced_custom_object(self, *args):
            return {
                "metadata": {"labels": {"hosting.antigravity.io/backup-source": "vm2"}},
                "status": {"phase": "Succeeded"},
            }

        def list_namespaced_custom_object(self, *args, **kwargs):
            return {"items": []}

    client.custom_api = Foreign()
    with pytest.raises(ValueError, match="не принадлежит"):
        client.restore_vm_backup("vm1", "vm2-backup-1")


def test_backup_restore_create_failure_keeps_current_disk_untouched():
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

    assert ("datavolumes", "vm1-disk") not in client.custom_api.deleted


def test_ambiguous_staged_restore_create_keeps_durable_marker():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreCustomApi()
    client.core_api = RestoreCoreApi()
    original_get = client.custom_api.get_namespaced_custom_object

    def fail_create(*_args, **_kwargs):
        raise ApiException(status=504, reason="create response lost")

    def fail_reconcile_get(group, version, namespace, plural, name):
        if plural == "datavolumes" and name != "vm1-backup-1":
            raise ApiException(status=500, reason="read unavailable")
        return original_get(group, version, namespace, plural, name)

    client.custom_api.create_namespaced_custom_object = fail_create
    client.custom_api.get_namespaced_custom_object = fail_reconcile_get
    cleared = []
    client.clear_backup_restore_operation = (
        lambda *args, **kwargs: cleared.append((args, kwargs))
    )

    with pytest.raises(ApiException, match="create response lost"):
        client.restore_vm_backup("vm1", "vm1-backup-1")

    assert cleared == []


class RestoreReconcileCustomApi:
    def __init__(self, target=None):
        self.target = target
        self.vm = _vm(running=True, annotations={
            K8sClient.BACKUP_RESTORE_OPERATION: "restore-op",
            K8sClient.BACKUP_RESTORE_STARTED_AT: "1",
            K8sClient.BACKUP_RESTORE_SOURCE: "vm1-backup-1",
            K8sClient.BACKUP_RESTORE_TARGET: "restore-op",
            K8sClient.BACKUP_RESTORE_OLD_PVC: "vm1-disk",
            K8sClient.BACKUP_RESTORE_RESTART_VM: "true",
        })

    def list_namespaced_custom_object(
        self, group, version, namespace, plural, label_selector=None,
    ):
        if plural == "datavolumes":
            return {"items": [self.target] if self.target else []}
        if plural == "virtualmachines":
            return {"items": [self.vm]}
        return {"items": []}

    def get_namespaced_custom_object(
        self, group, version, namespace, plural, name,
    ):
        if (
            plural == "datavolumes" and self.target
            and (self.target.get("metadata") or {}).get("name") == name
        ):
            return self.target
        raise ApiException(status=404)


@pytest.mark.parametrize(
    ("target", "expected_phase"),
    [
        (None, "Orphaned"),
        ({
            "metadata": {
                "name": "restore-op",
                "labels": {
                    "hosting.antigravity.io/restore-operation": "restore-op",
                },
            },
            "status": {"phase": "CloneInProgress"},
        }, "TimedOut"),
    ],
)
def test_staged_restore_orphan_and_timeout_are_reconciled(target, expected_phase):
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreReconcileCustomApi(target)
    client.BACKUP_RESTORE_ORPHAN_GRACE_SECONDS = 0
    client.BACKUP_RESTORE_MAX_RUNTIME_SECONDS = 0

    ready = client.backup_restores_awaiting_finish()

    assert len(ready) == 1
    assert ready[0]["phase"] == expected_phase
    assert ready[0]["operation"] == "restore-op"
    assert ready[0]["restart_vm"] is False


def test_restore_reconciler_finds_unlabelled_target_by_durable_marker():
    target = {
        "metadata": {"name": "restore-op", "labels": {}},
        "status": {"phase": "Succeeded"},
    }
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreReconcileCustomApi(target)

    ready = client.backup_restores_awaiting_finish()

    assert len(ready) == 1
    assert ready[0]["operation"] == "restore-op"
    assert ready[0]["phase"] == "Succeeded"


class RestoreFinishCustomApi:
    def __init__(self):
        self.vm = _vm(running=True, annotations={
            K8sClient.BACKUP_RESTORE_OPERATION: "restore-op",
            K8sClient.BACKUP_RESTORE_SOURCE: "vm1-backup-1",
            K8sClient.BACKUP_RESTORE_TARGET: "restore-op",
            K8sClient.BACKUP_RESTORE_OLD_PVC: "vm1-disk",
            K8sClient.BACKUP_RESTORE_RESTART_VM: "true",
        })
        self.events = []

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        if plural == "virtualmachines" and name == "vm1":
            return self.vm
        if plural == "datavolumes" and name == "restore-op":
            return {
                "metadata": {
                    "name": name,
                    "labels": {"hosting.antigravity.io/restore-operation": name},
                },
                "spec": {
                    "source": {"pvc": {"name": "vm1-backup-1"}},
                    "storage": {"resources": {"requests": {"storage": "20Gi"}}},
                },
                "status": {"phase": "Succeeded"},
            }
        raise ApiException(status=404)

    def patch_namespaced_custom_object(
        self, group, version, namespace, plural, name, body, **kwargs,
    ):
        self.events.append(("patch", plural, name, body))
        if plural == "virtualmachines" and isinstance(body, dict) and "spec" in body:
            self.vm["spec"].update(body["spec"])
        return body

    def delete_namespaced_custom_object(self, group, version, namespace, plural, name):
        self.events.append(("delete", plural, name))


class RestoreFinishCoreApi:
    def __init__(self, events):
        self.events = events

    def delete_namespaced_persistent_volume_claim(self, name, namespace):
        self.events.append(("delete", "persistentvolumeclaims", name))


def test_finished_backup_restore_switches_vm_before_deleting_old_disk():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreFinishCustomApi()
    client.core_api = RestoreFinishCoreApi(client.custom_api.events)
    client.stop_vm = lambda *_args, **_kwargs: client.custom_api.events.append(("stop", "vm1"))
    client.wait_for_vm_stopped = lambda *_args, **_kwargs: True
    client.get_vm = lambda *_args, **_kwargs: {"status": "Stopped"}
    client.start_vm = lambda *_args, **_kwargs: client.custom_api.events.append(("start", "vm1"))
    cleared = []
    client.clear_backup_restore_operation = (
        lambda vm, operation, namespace="default": cleared.append((vm, operation))
    )

    result = client.finish_backup_restore({
        "operation": "restore-op",
        "vm": "vm1",
        "backup": "vm1-backup-1",
        "target": "restore-op",
        "old_pvc": "vm1-disk",
        "restart_vm": True,
        "phase": "Succeeded",
    })

    events = client.custom_api.events
    switch_index = next(
        i for i, event in enumerate(events)
        if event[:3] == ("patch", "virtualmachines", "vm1")
        and isinstance(event[3], dict) and "spec" in event[3]
    )
    delete_index = events.index(("delete", "datavolumes", "vm1-disk"))
    assert switch_index < delete_index
    assert result == {"status": "succeeded", "vm": "vm1", "target": "restore-op"}
    assert ("start", "vm1") in events
    target_cleanup = next(
        event for event in events
        if event[:3] == ("patch", "datavolumes", "restore-op")
    )
    assert target_cleanup[3]["metadata"]["labels"][
        "hosting.antigravity.io/restore-operation"
    ] is None
    assert cleared == [("vm1", "restore-op")]


@pytest.mark.parametrize("phase", ["Failed", "Orphaned", "TimedOut"])
def test_failed_staged_restore_deletes_only_new_target(phase):
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreFinishCustomApi()
    client.core_api = RestoreFinishCoreApi(client.custom_api.events)
    cleared = []
    client.clear_backup_restore_operation = (
        lambda vm, operation, namespace="default": cleared.append((vm, operation))
    )

    result = client.finish_backup_restore({
        "operation": "restore-op",
        "vm": "vm1",
        "backup": "vm1-backup-1",
        "target": "restore-op",
        "old_pvc": "vm1-disk",
        "restart_vm": True,
        "phase": phase,
    })

    assert ("delete", "datavolumes", "restore-op") in client.custom_api.events
    assert ("delete", "persistentvolumeclaims", "restore-op") in client.custom_api.events
    assert ("delete", "datavolumes", "vm1-disk") not in client.custom_api.events
    expected = {"status": "failed", "vm": "vm1", "target": "restore-op"}
    if phase != "Failed":
        expected["reason"] = phase
    assert result == expected
    assert cleared == [("vm1", "restore-op")]


def test_orphan_cleanup_never_deletes_target_already_used_by_vm():
    client = K8sClient.__new__(K8sClient)
    client.custom_api = RestoreFinishCustomApi()
    client.custom_api.vm["spec"]["template"]["spec"]["volumes"][0][
        "dataVolume"
    ]["name"] = "restore-op"
    client.core_api = RestoreFinishCoreApi(client.custom_api.events)

    with pytest.raises(RuntimeError, match="системным диском"):
        client.finish_backup_restore({
            "operation": "restore-op",
            "vm": "vm1",
            "target": "restore-op",
            "old_pvc": "vm1-disk",
            "restart_vm": False,
            "phase": "Orphaned",
        })

    assert ("delete", "datavolumes", "restore-op") not in client.custom_api.events
    assert (
        "delete", "persistentvolumeclaims", "restore-op"
    ) not in client.custom_api.events


def test_stop_is_refused_while_storage_operation_is_active(monkeypatch):
    monkeypatch.setattr(vm_api, "check_vm_ownership", lambda *_args, **_kwargs: None)

    class BusyClient:
        stopped = False

        def ensure_no_backup_operation(self, _name):
            raise ValueError("restore is active")

        def stop_vm(self, _name):
            self.stopped = True

    client = BusyClient()
    with pytest.raises(HTTPException) as exc:
        vm_api.stop_vm("vm1", client, object())

    assert exc.value.status_code == 409
    assert client.stopped is False


class SnapshotClient:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.deleted = []

    def list_vm_snapshots(self, vm_name):
        return self.snapshots

    def delete_vm_snapshot(self, name):
        self.deleted.append(name)

    def ensure_no_backup_operation(self, _name):
        return None


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
