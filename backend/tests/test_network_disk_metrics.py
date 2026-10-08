from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from app.core.capacity import network_disks_lvm_reserved_gb
from app.models.models import UserVolume
from test_s3_archives import db_env


def pvc(name, storage_class, size="1Gi"):
    return NS(metadata=NS(name=name), spec=NS(storage_class_name=storage_class,
        resources=NS(requests={"storage": size})))


def test_only_network_disks_with_actual_lvm_claims_are_counted(db_env):
    factory, _ = db_env
    with factory() as db:
        db.add_all([
            UserVolume(name="vol-1-local", size_gb=10, owner_id=1),
            UserVolume(name="vol-1-lvm", size_gb=5, owner_id=1),
            UserVolume(name="vol-1-attached", size_gb=3, owner_id=1, attached_vm_id=1),
            UserVolume(name="vol-1-missing", size_gb=30, owner_id=1),
        ])
        db.commit()
        k8s = MagicMock()
        k8s.core_api.list_namespaced_persistent_volume_claim.return_value = NS(items=[
            pvc("vol-1-local", "local-path"), pvc("vol-1-lvm", "openebs-lvm"),
            pvc("vol-1-attached", "openebs-lvm"), pvc("vm1-disk", "openebs-lvm"),
            pvc("backup-vm1", "openebs-lvm"), pvc("db-vm1", "openebs-lvm"),
        ])
        assert network_disks_lvm_reserved_gb(db, k8s) == 8.0
        k8s.core_api.list_namespaced_persistent_volume_claim.assert_called_once_with(namespace="default")


def test_user_report_local_path_network_disk_does_not_reserve_unused_lvm(db_env):
    factory, _ = db_env
    with factory() as db:
        db.add(UserVolume(name="vol-1-test", size_gb=10, owner_id=1))
        db.commit()
        k8s = MagicMock()
        k8s.core_api.list_namespaced_persistent_volume_claim.return_value = NS(items=[
            pvc("test-disk", "local-path"), pvc("restore-test-disk-0", "local-path"),
            pvc("vol-1-test", "local-path"),
        ])
        assert network_disks_lvm_reserved_gb(db, k8s) == 0.0


def test_empty_network_volume_list_needs_no_kubernetes_request(db_env):
    factory, _ = db_env
    with factory() as db:
        k8s = MagicMock()
        assert network_disks_lvm_reserved_gb(db, k8s) == 0.0
        k8s.core_api.list_namespaced_persistent_volume_claim.assert_not_called()


def test_unavailable_kubernetes_is_not_reported_as_zero_reserved(db_env):
    factory, _ = db_env
    with factory() as db:
        db.add(UserVolume(name="vol-1-test", size_gb=10, owner_id=1))
        db.commit()
        k8s = MagicMock()
        k8s.core_api.list_namespaced_persistent_volume_claim.side_effect = RuntimeError("Kubernetes недоступен")
        with pytest.raises(RuntimeError, match="Kubernetes недоступен"):
            network_disks_lvm_reserved_gb(db, k8s)
