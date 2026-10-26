from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from kubernetes.client.rest import ApiException

from app.api import volumes
from app.core import capacity as cap
from app.core.config import settings
from app.core.k8s_client import K8sClient
from app.models.models import UserVolume
from test_s3_archives import db_env
from test_network_disk_metrics import pvc


def dv(name, size, storage_class="openebs-lvm"):
    return {"metadata": {"name": name}, "spec": {"storage": {
        "storageClassName": storage_class, "resources": {"requests": {"storage": size}}}}}


@pytest.fixture
def create_env(db_env, monkeypatch):
    factory, _ = db_env
    monkeypatch.setattr(volumes, "SessionLocal", factory)
    monkeypatch.setattr(settings, "STORAGE_CLASS", "local-path")
    monkeypatch.setattr(settings, "NETWORK_STORAGE_CLASS", "openebs-lvm")
    monkeypatch.setattr(cap, "lock_host_capacity", lambda db: None)
    monkeypatch.setattr(cap, "read_lvm_pool_gb", lambda: {"active": True, "total_gb": 10.0, "free_gb": 10.0})
    k8s = K8sClient.__new__(K8sClient)
    k8s.storage_api = MagicMock()
    k8s.storage_api.read_storage_class.return_value = NS(
        provisioner="local.csi.openebs.io", parameters={"volgroup": "vg-aegis"})
    k8s.core_api = MagicMock()
    k8s.core_api.list_namespaced_persistent_volume_claim.return_value = NS(items=[
        pvc("test-disk", "local-path", "22763326669"),
        pvc("restore-test-disk-0", "local-path", "22763326669"),
        pvc("vol-1-old", "local-path", "10Gi"),
    ])
    k8s.custom_api = MagicMock()
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": []}
    return factory, k8s, NS(id=1, role="admin", username="one")


def test_new_network_disk_uses_lvm_block_without_changing_default_vm_storage(create_env):
    factory, k8s, user = create_env
    result = volumes.create_volume(volumes.VolumeCreateRequest(name="new", size_gb=2), k8s, user)
    assert result.size_gb == 2
    body = k8s.custom_api.create_namespaced_custom_object.call_args.kwargs["body"]
    assert body["spec"]["storage"]["storageClassName"] == "openebs-lvm"
    assert body["spec"]["storage"]["volumeMode"] == "Block"
    assert body["spec"]["storage"]["resources"]["requests"]["storage"] == "2Gi"
    with factory() as db:
        assert db.query(UserVolume).one().name == "vol-1-new"
    k8s.create_pvc("vm-default", 20)
    body = k8s.custom_api.create_namespaced_custom_object.call_args.kwargs["body"]
    assert body["spec"]["storage"]["storageClassName"] == "local-path"
    assert body["spec"]["storage"]["volumeMode"] == "Filesystem"
    assert settings.STORAGE_CLASS == "local-path"


def test_pending_datavolume_reserves_pool_space_before_pvc_exists(create_env):
    factory, k8s, user = create_env
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": [dv("vol-1-pending", "8Gi")]}
    with pytest.raises(HTTPException) as exc:
        volumes.create_volume(volumes.VolumeCreateRequest(name="new", size_gb=3), k8s, user)
    assert exc.value.status_code == 400
    assert "LVM-пуле" in exc.value.detail
    k8s.custom_api.create_namespaced_custom_object.assert_not_called()
    with factory() as db:
        assert db.query(UserVolume).count() == 0


def test_lvm_pvc_and_its_datavolume_are_not_double_counted(create_env):
    _, k8s, _ = create_env
    k8s.core_api.list_namespaced_persistent_volume_claim.return_value.items.append(pvc("vol-1-existing", "openebs-lvm", "3Gi"))
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": [
        dv("vol-1-existing", "3Gi"), dv("vol-1-pending", "2Gi"), dv("local-vm", "20Gi", "local-path")]}
    assert cap.lvm_storage_allocations_gb(k8s) == {"vol-1-existing": 3.0, "vol-1-pending": 2.0}


@pytest.mark.parametrize("missing", ["class", "api", "pool", "allocation-api", "wrong-pool", "wrong-provisioner", "local-config"])
def test_network_disks_never_fall_back_to_local_path(create_env, monkeypatch, missing):
    factory, k8s, user = create_env
    if missing == "class":
        k8s.storage_api.read_storage_class.side_effect = ApiException(status=404)
    elif missing == "api":
        k8s.storage_api.read_storage_class.side_effect = ApiException(status=403)
    elif missing == "pool":
        monkeypatch.setattr(cap, "read_lvm_pool_gb", lambda: {"active": False, "total_gb": 0.0, "free_gb": 0.0})
    elif missing == "allocation-api":
        k8s.custom_api.list_namespaced_custom_object.side_effect = ApiException(status=503)
    elif missing == "wrong-pool":
        k8s.storage_api.read_storage_class.return_value.parameters = {"volgroup": "other-vg"}
    elif missing == "wrong-provisioner":
        k8s.storage_api.read_storage_class.return_value.provisioner = "other.csi.io"
    else:
        monkeypatch.setattr(settings, "NETWORK_STORAGE_CLASS", "local-path")
    with pytest.raises(HTTPException) as exc:
        volumes.create_volume(volumes.VolumeCreateRequest(name="new", size_gb=2), k8s, user)
    assert exc.value.status_code in (400, 503)
    k8s.custom_api.create_namespaced_custom_object.assert_not_called()
    with factory() as db:
        assert db.query(UserVolume).count() == 0


def test_network_metrics_include_pending_lvm_disks_under_local_default(create_env):
    factory, k8s, _ = create_env
    with factory() as db:
        db.add(UserVolume(name="vol-1-pending", owner_id=1, size_gb=4))
        db.commit()
        k8s.custom_api.list_namespaced_custom_object.return_value = {"items": [dv("vol-1-pending", "4Gi")]}
        assert cap.network_disks_lvm_reserved_gb(db, k8s) == 4


def test_vm_creation_never_uses_or_checks_lvm_pool_even_with_legacy_env(create_env, monkeypatch):
    """Даже при маленьком LVM-пуле (20 ГБ) и legacy STORAGE_CLASS=openebs-lvm
    создание ВМ с системным диском 60 ГБ проверяет локальный диск хоста и
    создаёт системный диск на local-path, а не на LVM."""
    from app.api.vms import VMCreationRequest, generate_linux_manifest, generate_windows_manifest
    from app.core.config import Settings

    factory, k8s, _ = create_env
    monkeypatch.setenv("STORAGE_CLASS", "openebs-lvm")
    assert Settings().STORAGE_CLASS == "local-path"

    monkeypatch.setattr(settings, "STORAGE_CLASS", "openebs-lvm")
    monkeypatch.setattr(cap, "read_lvm_pool_gb", lambda: {"active": True, "total_gb": 20.0, "free_gb": 5.0})
    monkeypatch.setattr(cap, "host_totals", lambda: {
        "cpu": 8, "ram_gb": 32.0, "ram_used_gb": 4.0, "disk_gb": 500.0, "disk_free_gb": 400.0,
    })
    monkeypatch.setattr(cap, "backups_total_gb", lambda *_a, **_kw: 0.0)

    with factory() as db:
        cap.ensure_storage_capacity(db, extra_gb=60, k8s=k8s)

    req = VMCreationRequest(name="vm60", os_type="ubuntu", cpu_cores=2, memory_gb=2, disk_gb=60)
    linux_manifest = generate_linux_manifest(req, "secret123")
    assert linux_manifest["spec"]["dataVolumeTemplates"][0]["spec"]["storage"]["storageClassName"] == "local-path"

    win_req = VMCreationRequest(name="win60", os_type="windows", cpu_cores=2, memory_gb=4, disk_gb=60)
    win_manifest = generate_windows_manifest(win_req)
    for dvt in win_manifest["spec"]["dataVolumeTemplates"]:
        assert dvt["spec"]["storage"]["storageClassName"] == "local-path"
