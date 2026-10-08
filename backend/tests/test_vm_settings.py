from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from kubernetes import client
from urllib3.response import HTTPResponse

from app.core.k8s_client import K8sClient
from app.api import vms
from app.models.models import VMTask
from test_s3_archives import db_env


def root_vm():
    return {"spec": {"template": {"spec": {"domain": {"devices": {"disks": [
        {"name": "iso", "cdrom": {}}, {"name": "root", "disk": {}}]}},
        "volumes": [{"name": "iso", "dataVolume": {"name": "vm1-iso"}},
                    {"name": "root", "dataVolume": {"name": "restore-active-disk-0"}}]}}}}


def resize_client(storage="20Gi", expandable=True):
    k8s = K8sClient.__new__(K8sClient)
    k8s.custom_api = NS(get_namespaced_custom_object=lambda *args: root_vm())
    pvc = NS(metadata=NS(name="restore-active-disk-0"),
             spec=NS(resources=NS(requests={"storage": storage}), storage_class_name="local-path"))
    k8s.core_api = MagicMock()
    k8s.core_api.read_namespaced_persistent_volume_claim.return_value = pvc
    k8s.storage_api = MagicMock()
    k8s.storage_api.read_storage_class.return_value = NS(allow_volume_expansion=expandable)
    return k8s


def test_cpu_ram_resize_uses_valid_merge_patch_with_real_sdk(monkeypatch):
    api = client.ApiClient(client.Configuration())
    k8s = K8sClient.__new__(K8sClient)
    k8s.custom_api = client.CustomObjectsApi(api)
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        assert kwargs["headers"]["Content-Type"] == "application/merge-patch+json"
        assert isinstance(kwargs["body"], dict), "JSON Patch list is invalid with Merge Patch"
        return HTTPResponse(body=b'{}', status=200, headers={"Content-Type": "application/json"})
    monkeypatch.setattr(api, "request", request)
    try:
        k8s.resize_vm_resources("vm1", 4, 8)
    finally:
        api.close()
    domain = calls[0][2]["body"]["spec"]["template"]["spec"]["domain"]
    assert domain == {"cpu": {"cores": 4}, "resources": {"requests": {"memory": "8Gi"}}}
    assert calls[0][0] == "PATCH"


def test_disk_resize_targets_current_manifest_disk_not_name_prefix():
    k8s = resize_client()
    result = k8s.resize_vm_disk("vm1", 30)
    assert result["pvc"] == "restore-active-disk-0"
    k8s.core_api.patch_namespaced_persistent_volume_claim.assert_called_once_with(
        "restore-active-disk-0", "default", {"spec": {"resources": {"requests": {"storage": "30Gi"}}}})
    k8s.core_api.list_namespaced_persistent_volume_claim.assert_not_called()


@pytest.mark.parametrize("storage", ["20Gi", "22763326669"])
def test_unchanged_disk_does_not_require_expansion_or_shrink_cdi_overhead(storage):
    k8s = resize_client(storage=storage, expandable=False)
    assert k8s.resize_vm_disk("vm1", 20)["status"] == "unchanged"
    k8s.core_api.patch_namespaced_persistent_volume_claim.assert_not_called()
    k8s.storage_api.read_storage_class.assert_not_called()


def test_unsupported_storage_resize_fails_before_patching():
    k8s = resize_client(expandable=False)
    with pytest.raises(ValueError, match="не поддерживает расширение"):
        k8s.resize_vm_disk("vm1", 30)
    k8s.core_api.patch_namespaced_persistent_volume_claim.assert_not_called()


@pytest.fixture
def settings_api(db_env, monkeypatch):
    factory, _s3 = db_env
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr(vms, "check_vm_ownership", lambda *args, **kwargs: None)
    k8s = MagicMock()
    k8s.get_vm.return_value = {"status": "Stopped", "cpu_cores": 2, "memory": "2Gi", "disks": []}
    k8s.query_prometheus.return_value = []
    user = NS(id=1, role="admin")
    return factory, k8s, user


def test_settings_are_persisted_and_available_after_page_reload(settings_api):
    factory, k8s, user = settings_api
    request = vms.VMSettingsUpdateRequest(cpu_cores=4, memory_gb=8, disk_gb=30,
        disk_read_mbs=20, disk_write_mbs=10, disk_read_iops=100, disk_write_iops=200)
    assert vms.update_vm_settings("vm1", request, k8s, user)["status"] == "success"
    with factory() as db:
        vm = db.query(VMTask).filter(VMTask.name == "vm1").one()
        assert (vm.cpu_cores, vm.memory_gb, vm.disk_gb) == (4, 8, 30)
        assert (vm.disk_read_mbs, vm.disk_write_mbs, vm.disk_read_iops, vm.disk_write_iops) == (20, 10, 100, 200)
    details = vms.get_vm_details("vm1", k8s, user)
    assert details["disk_gb"] == 30  # нет dataVolumeTemplates после отката
    assert details["memory_gb"] == 8
    assert details["disk_read_mbs"] == 20
    k8s.resize_vm_resources.assert_called_once_with("vm1", 4, 8)
    k8s.resize_vm_disk.assert_called_once_with("vm1", 30)


def test_unsupported_disk_does_not_leave_unsaved_cpu_ram_changes(settings_api):
    factory, k8s, user = settings_api
    k8s.validate_vm_disk_resize.side_effect = ValueError("local-path не поддерживает расширение")
    request = vms.VMSettingsUpdateRequest(cpu_cores=4, memory_gb=8, disk_gb=30)
    with pytest.raises(HTTPException) as error:
        vms.update_vm_settings("vm1", request, k8s, user)
    assert error.value.status_code == 400
    assert "local-path" in error.value.detail
    k8s.resize_vm_resources.assert_not_called()
    with factory() as db:
        assert db.query(VMTask).one().cpu_cores != 4


def test_cannot_reduce_reserved_disk_size(settings_api):
    factory, k8s, user = settings_api
    with factory() as db:
        db.query(VMTask).one().disk_gb = 40
        db.commit()
    with pytest.raises(HTTPException) as error:
        vms.update_vm_settings("vm1", vms.VMSettingsUpdateRequest(cpu_cores=2, memory_gb=2, disk_gb=20), k8s, user)
    assert error.value.status_code == 400
    k8s.resize_vm_disk.assert_not_called()


def test_only_limits_can_be_saved_without_disk_expansion(settings_api):
    factory, k8s, user = settings_api
    with factory() as db:
        vm = db.query(VMTask).one()
        vm.cpu_cores, vm.memory_gb, vm.disk_gb = 2, 2, 20
        db.commit()
    vms.update_vm_settings("vm1", vms.VMSettingsUpdateRequest(
        cpu_cores=2, memory_gb=2, disk_gb=20, disk_read_iops=100), k8s, user)
    k8s.validate_vm_disk_resize.assert_not_called()
    k8s.resize_vm_resources.assert_not_called()
    k8s.resize_vm_disk.assert_not_called()
