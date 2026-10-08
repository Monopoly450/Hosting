from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from kubernetes.client.rest import ApiException

from app.api import volumes
from app.models.models import UserVolume, VMTask
from app.services.vm_network_disks import network_disk_connections
from test_s3_archives import db_env


def manifest(name="vm1", *, plural="virtualmachines", hotplug=False, source="persistentVolumeClaim"):
    volume = {"name": "net-pvc-0", source: {
        "claimName" if source == "persistentVolumeClaim" else "name": "vol-1-test",
        "hotpluggable": hotplug,
    }}
    spec = {"volumes": [volume]}
    return {"metadata": {"name": name}, "spec": {"template": {"spec": spec}} if plural == "virtualmachines" else spec}


@pytest.fixture
def env(db_env, monkeypatch):
    factory, _ = db_env
    monkeypatch.setattr(volumes, "SessionLocal", factory)
    with factory() as db:
        db.query(VMTask).one().status = "Running"
        db.add(UserVolume(id=1, name="vol-1-test", owner_id=1, size_gb=1))
        db.commit()
    k8s = MagicMock()
    resources = {"virtualmachines": [], "virtualmachineinstances": []}
    k8s.custom_api.list_namespaced_custom_object.side_effect = lambda _g, _v, _ns, plural: {"items": resources[plural]}
    k8s.get_vm.return_value = {"status": "Running"}
    return factory, k8s, resources, NS(id=1, role="student", username="one")


@pytest.mark.parametrize("plural", ["virtualmachines", "virtualmachineinstances"])
@pytest.mark.parametrize("source", ["persistentVolumeClaim", "dataVolume"])
def test_creation_disk_is_connected_in_old_and_new_manifests_without_db_changes(env, plural, source):
    factory, k8s, resources, user = env
    resources[plural] = [manifest(plural=plural, source=source)]
    result = volumes.list_volumes(user, k8s)[0]
    assert result.status == "Attached"
    assert result.attached_vm_name == "vm1"
    assert result.attachment_type == "creation"
    assert not result.can_detach and not result.can_delete
    with factory() as db:
        row = db.query(UserVolume).one()
        assert row.attached_vm_id is None and row.status == "Available"
    k8s.custom_api.patch_namespaced_custom_object.assert_not_called()


def test_vm_and_vmi_are_deduplicated_and_stopped_vm_keeps_connection(env):
    factory, k8s, resources, user = env
    resources["virtualmachines"] = [manifest()]
    resources["virtualmachineinstances"] = [manifest(plural="virtualmachineinstances")]
    with factory() as db:
        db.query(VMTask).one().status = "Stopped"
        db.commit()
    assert volumes.list_volumes(user, k8s)[0].attached_vm_name == "vm1"
    resources["virtualmachineinstances"] = []
    assert volumes.list_volumes(user, k8s)[0].status == "Attached"


@pytest.mark.parametrize("task_status", ["Pending", "Provisioning"])
def test_selected_disk_is_reserved_until_manifest_exists(env, task_status):
    factory, k8s, resources, user = env
    with factory() as db:
        task = db.query(VMTask).one()
        task.status = task_status
        task.network_drives = "nfs.example:/shared, vol-1-test"
        db.commit()
    result = volumes.list_volumes(user, k8s)[0]
    assert result.status == "Reserved" and result.attached_vm_name == "vm1"
    assert not result.can_detach and not result.can_delete
    resources["virtualmachines"] = [manifest()]
    assert volumes.list_volumes(user, k8s)[0].status == "Attached"


@pytest.mark.parametrize("status", ["Running", "Stopped", "Error"])
def test_historical_creation_input_does_not_fake_an_attachment(env, status):
    factory, k8s, _, user = env
    with factory() as db:
        task = db.query(VMTask).one()
        task.status = status
        task.network_drives = "vol-1-test"
        db.commit()
    result = volumes.list_volumes(user, k8s)[0]
    assert result.status == "Available" and result.attached_vm_name is None
    assert result.can_delete


def test_accepted_hotplug_request_reserves_disk_before_template_is_updated(env):
    _, k8s, resources, user = env
    resources["virtualmachines"] = [{"metadata": {"name": "vm1"}, "status": {"volumeRequests": [
        {"addVolumeOptions": {"name": "test", "volumeSource": {"persistentVolumeClaim": {"claimName": "vol-1-test"}}}},
    ]}}]
    result = volumes.list_volumes(user, k8s)[0]
    assert result.status == "Reserved" and result.attached_vm_name == "vm1"


def test_hotplug_disk_uses_actual_volume_name_for_detach(env):
    factory, k8s, resources, user = env
    resources["virtualmachines"] = [manifest(hotplug=True)]
    result = volumes.list_volumes(user, k8s)[0]
    assert result.can_detach and result.attachment_type == "hotplug"
    volumes.detach_volume(1, k8s, user)
    k8s.remove_vm_volume.assert_called_once_with("vm1", volume_name="net-pvc-0")
    resources["virtualmachines"] = []
    with factory() as db:
        row = db.query(UserVolume).one()
        assert row.status == "Available" and row.attached_vm_id is None
    assert volumes.list_volumes(user, k8s)[0].status == "Available"


def test_existing_db_hotplug_state_survives_controller_delay(env):
    factory, k8s, _, user = env
    with factory() as db:
        row = db.query(UserVolume).one()
        row.status = "Attached"
        row.attached_vm_id = 1
        db.commit()
    result = volumes.list_volumes(user, k8s)[0]
    assert result.status == "Attached" and result.can_detach
    volumes.detach_volume(1, k8s, user)
    k8s.remove_vm_volume.assert_called_once_with("vm1", volume_name="test")


def test_failed_auto_detach_never_deletes_a_connected_pvc(env):
    factory, k8s, resources, user = env
    resources["virtualmachines"] = [manifest(hotplug=True)]
    k8s.remove_vm_volume.side_effect = RuntimeError("API unavailable")
    with pytest.raises(HTTPException) as exc:
        volumes.delete_volume(1, k8s, user)
    assert exc.value.status_code == 500
    k8s.delete_pvc.assert_not_called()
    with factory() as db:
        assert db.query(UserVolume).count() == 1


def test_disk_connected_to_unmanaged_vm_cannot_be_deleted(env):
    _, k8s, resources, user = env
    resources["virtualmachines"] = [manifest("external-vm", hotplug=True)]
    with pytest.raises(HTTPException) as exc:
        volumes.delete_volume(1, k8s, user)
    assert exc.value.status_code == 400
    k8s.delete_pvc.assert_not_called()


@pytest.mark.parametrize("operation", ["attach", "detach", "delete"])
@pytest.mark.parametrize("connection", ["creation", "reserved", "multiple"])
def test_busy_creation_disk_cannot_be_reused_hot_unplugged_or_deleted(env, operation, connection):
    factory, k8s, resources, user = env
    if connection == "reserved":
        with factory() as db:
            task = db.query(VMTask).one()
            task.status = "Pending"
            task.network_drives = "vol-1-test"
            db.commit()
    else:
        resources["virtualmachines"] = [manifest()]
        if connection == "multiple":
            resources["virtualmachines"].append(manifest("another-vm"))
    with pytest.raises(HTTPException) as exc:
        if operation == "attach":
            volumes.attach_volume(1, "vm1", k8s, user)
        else:
            getattr(volumes, f"{operation}_volume")(1, k8s, user)
    assert exc.value.status_code == 400
    k8s.add_vm_volume.assert_not_called()
    k8s.remove_vm_volume.assert_not_called()
    k8s.delete_pvc.assert_not_called()
    with factory() as db:
        assert db.query(UserVolume).count() == 1


@pytest.mark.parametrize("operation", ["list", "attach", "detach", "delete"])
def test_cluster_error_never_marks_disk_free_or_allows_destructive_operation(env, operation):
    _, k8s, _, user = env
    k8s.custom_api.list_namespaced_custom_object.side_effect = ApiException(status=503)
    with pytest.raises(HTTPException) as exc:
        if operation == "list":
            volumes.list_volumes(user, k8s)
        elif operation == "attach":
            volumes.attach_volume(1, "vm1", k8s, user)
        else:
            getattr(volumes, f"{operation}_volume")(1, k8s, user)
    assert exc.value.status_code == 503
    k8s.delete_pvc.assert_not_called()


def test_empty_list_does_not_require_kubernetes(env):
    factory, k8s, _, _ = env
    with factory() as db:
        assert network_disk_connections(db, k8s, []) == {}
    k8s.custom_api.list_namespaced_custom_object.assert_not_called()


def test_normal_user_only_sees_own_disks_and_admin_sees_all(env):
    factory, k8s, _, user = env
    with factory() as db:
        db.add(UserVolume(id=2, name="vol-2-other", owner_id=2, size_gb=1))
        db.commit()
    assert [v.name for v in volumes.list_volumes(user, k8s)] == ["test"]
    assert len(volumes.list_volumes(NS(id=1, role="admin"), k8s)) == 2


@pytest.mark.parametrize("operation", ["attach", "detach", "delete"])
def test_other_user_cannot_touch_disk_or_trigger_cluster_lookup(env, operation):
    _, k8s, _, _ = env
    other = NS(id=2, role="student")
    with pytest.raises(HTTPException) as exc:
        if operation == "attach":
            volumes.attach_volume(1, "vm1", k8s, other)
        else:
            getattr(volumes, f"{operation}_volume")(1, k8s, other)
    assert exc.value.status_code == 403
    k8s.custom_api.list_namespaced_custom_object.assert_not_called()
