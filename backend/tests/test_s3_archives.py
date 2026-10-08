import copy
import json
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException
from kubernetes.client.rest import ApiException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.models import User, VMTask, VMArchive
from app.services import vm_archives as archives
from app.services.backup_storage import bucket_name, database_location


@compiles(JSONB, "sqlite")
def jsonb_as_json(_type, _compiler, **_kwargs):
    return "JSON"


def vm_manifest():
    return {
        "metadata": {"name": "vm1", "uid": "vm-uid", "resourceVersion": "1", "annotations": {}},
        "spec": {"running": True, "template": {"spec": {
            "domain": {"devices": {"disks": [
                {"name": "root", "disk": {}}, {"name": "data", "disk": {}},
                {"name": "iso", "cdrom": {}}, {"name": "cloudinit", "disk": {}},
            ]}},
            "volumes": [
                {"name": "root", "dataVolume": {"name": "root-pvc"}},
                {"name": "data", "persistentVolumeClaim": {"claimName": "data-pvc"}},
                {"name": "iso", "dataVolume": {"name": "iso-pvc"}},
                {"name": "cloudinit", "cloudInitNoCloud": {"userData": "test"}},
            ],
        }}, "dataVolumeTemplates": [{"metadata": {"name": "root-pvc"}}]},
    }


@pytest.fixture
def db_env(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=1, username="one", password_hash="x"), User(id=2, username="two", password_hash="x")])
        db.add(VMTask(id=1, name="vm1", owner_id=1, os_type="ubuntu", disk_gb=2))
        db.commit()
    monkeypatch.setattr(archives, "SessionLocal", factory)
    monkeypatch.setattr(archives, "ensure_backup_bucket", lambda db, owner, s3: bucket_name(owner))
    s3 = FakeS3()
    monkeypatch.setattr(archives, "s3_client", lambda: s3)
    monkeypatch.setattr("app.core.capacity.host_totals", lambda: {"disk_free_gb": 1000})
    yield factory, s3
    engine.dispose()


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.removed = []

    def bucket_exists(self, name):
        return True

    def put_object(self, bucket, key, stream, length, **kwargs):
        self.uploads.append((bucket, key, length, kwargs))
        self.objects[(bucket, key)] = stream.read()

    def stat_object(self, bucket, key):
        return NS(size=len(self.objects[(bucket, key)]), etag="valid-etag")

    def list_objects(self, bucket, prefix, recursive=True):
        return [NS(object_name=key) for b, key in self.objects if b == bucket and key.startswith(prefix)]

    def remove_object(self, bucket, key):
        self.removed.append((bucket, key))
        self.objects.pop((bucket, key), None)


class FakeK8s:
    def __init__(self):
        self.vm = vm_manifest()
        self.custom_api = self
        self.core_api = self
        self.actions = []
        self.dvs = {}
        self.patches = []

    def ensure_no_backup_operation(self, name):
        return None

    def list_namespaced_custom_object(self, *args, **kwargs):
        return {"items": []}

    def get_vm(self, name):
        return {"status": "Running" if self.vm["spec"].get("running") else "Stopped"}

    def get_namespaced_custom_object(self, group, version, ns, plural, name):
        if plural == "virtualmachines":
            return copy.deepcopy(self.vm)
        if name in self.dvs:
            return self.dvs[name]
        raise ApiException(status=404)

    def acquire_s3_operation(self, name, operation):
        self.actions.append(("lock", operation))
        return copy.deepcopy(self.vm)

    def clear_s3_operation(self, name, operation):
        self.actions.append(("unlock", operation))

    def stop_vm(self, name):
        self.actions.append(("stop", name))
        self.vm["spec"]["running"] = False

    def start_vm(self, name):
        self.actions.append(("start", name))
        self.vm["spec"]["running"] = True

    def wait_for_vm_stopped(self, name):
        return True

    def read_namespaced_persistent_volume_claim(self, name, ns):
        return NS(spec=NS(access_modes=["ReadWriteOnce"], volume_mode="Filesystem",
                         storage_class_name="local-path", resources=NS(requests={"storage": "1Gi"})))

    def create_namespaced_custom_object(self, group, version, ns, plural, body):
        self.dvs[body["metadata"]["name"]] = {**body, "status": {"phase": "Pending"}}
        return self.dvs[body["metadata"]["name"]]

    def delete_namespaced_custom_object(self, group, version, ns, plural, name):
        self.actions.append(("delete", name))
        self.dvs.pop(name, None)

    def _patch_vm_json(self, name, body):
        self.patches.append(body)
        for patch in body:
            if patch["op"] == "replace" and patch["path"] == "/spec":
                self.vm["spec"] = patch["value"]

    def _annotation_json_path(self, key):
        return "/metadata/annotations/" + key

    S3_OPERATION = "s3-operation"


def new_record(factory, kind="backup", **overrides):
    with factory() as db:
        row = VMArchive(
            name="s3-backup-1", vm_name="vm1", owner_id=1, kind=kind,
            bucket=bucket_name(1), prefix="vms/1/backup/s3-backup-1/", status="Pending", progress=0,
            manifest={"vm_uid": "vm-uid", "vm_id": 1, "label": "before-change",
                      "vm_spec": vm_manifest()["spec"], "volumes": archives.disk_volumes(vm_manifest())},
            restore_data={},
        )
        for key, value in overrides.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()
        return row.name


def test_all_data_disks_are_selected_but_iso_and_cloudinit_are_excluded():
    assert archives.disk_volumes(vm_manifest()) == [
        {"volume_name": "root", "pvc": "root-pvc"}, {"volume_name": "data", "pvc": "data-pvc"},
    ]


def test_users_get_distinct_buckets_and_database_prefixes():
    assert bucket_name(1) != bucket_name(2)
    assert database_location(NS(owner_id=2, id=50)) == ("aegis-backups-u2", "databases/50/")
    with pytest.raises(ValueError):
        bucket_name(None)


def test_enqueue_persists_owner_bucket_and_does_not_stop_vm(db_env):
    factory, _s3 = db_env
    k8s = FakeK8s()
    result = archives.enqueue("vm1", "snapshot", k8s, label="before-install")
    assert result["bucket"] == bucket_name(1)
    assert not k8s.actions
    with factory() as db:
        row = db.get(VMArchive, result["name"])
        assert row.owner_id == 1
        assert row.manifest["label"] == "before-install"
    with pytest.raises(HTTPException) as error:
        archives.enqueue("vm1", "backup", k8s)
    assert error.value.status_code == 409


def test_windows_is_rejected_before_bucket_or_disk_work(db_env):
    factory, s3 = db_env
    with factory() as db:
        db.get(VMTask, 1).os_type = "windows"
        db.commit()
    with pytest.raises(HTTPException) as error:
        archives.enqueue("vm1", "backup", FakeK8s())
    assert error.value.status_code == 400
    assert not s3.uploads


def test_archive_from_other_owner_is_never_returned_or_deleted(db_env):
    factory, s3 = db_env
    name = new_record(factory)
    with factory() as db:
        row = db.get(VMArchive, name)
        row.owner_id = 2
        row.status = "Succeeded"
        db.commit()
    assert archives.list_archives("vm1", "backup") == []
    with pytest.raises(HTTPException) as error:
        archives.delete_archive("vm1", name, "backup")
    assert error.value.status_code == 404
    assert not s3.removed


def test_active_archive_cannot_be_deleted(db_env):
    factory, s3 = db_env
    name = new_record(factory)
    with pytest.raises(HTTPException) as error:
        archives.delete_archive("vm1", name, "backup")
    assert error.value.status_code == 409
    assert not s3.removed


def test_capture_streams_all_disks_and_only_then_commits_manifest(db_env, monkeypatch):
    factory, s3 = db_env
    name = new_record(factory)
    k8s = FakeK8s()
    status = {"links": {"internal": {"volumes": [
        {"name": "root", "formats": [{"format": "raw", "url": "https://export/root"}]},
        {"name": "data", "formats": [{"format": "raw", "url": "https://export/data"}]},
    ]}}}
    monkeypatch.setattr(archives, "_wait_export", lambda *args: (status, "token"))

    class Body(BytesIO):
        def release_conn(self):
            pass

    monkeypatch.setattr(archives, "_open_export", lambda *args: (NS(close=lambda: None), Body(b"complete-disk")))
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    with factory() as db:
        row = db.get(VMArchive, name)
        archives._capture(db, k8s, row)
        # Не показываем готовой до возврата питания и снятия блокировки.
        assert row.status == "Finalizing"
        archives._capture(db, k8s, row)
        assert row.status == "Succeeded"
        assert row.operation is None
        assert len(row.manifest["disks"]) == 2
        assert all(d["claim"]["storageClassName"] == "local-path" for d in row.manifest["disks"])
    assert [upload[2] for upload in s3.uploads[:2]] == [-1, -1]
    assert s3.uploads[-1][1].endswith("manifest.json")
    assert ("stop", "vm1") in k8s.actions and ("start", "vm1") in k8s.actions


def test_failed_upload_never_marks_the_copy_ready(db_env, monkeypatch):
    factory, s3 = db_env
    name = new_record(factory)
    monkeypatch.setattr(archives, "_wait_export", lambda *args: (_ for _ in ()).throw(RuntimeError("export unavailable")))
    with factory() as db:
        row = db.get(VMArchive, name)
        with pytest.raises(RuntimeError):
            archives._capture(db, FakeK8s(), row)
        assert row.status != "Succeeded"
        assert not row.manifest.get("disks")
    assert not s3.uploads


def completed_restore(factory, restore_state="Finalizing"):
    name = new_record(factory, status="Succeeded", operation="restore-1",
                      restore_state=restore_state, restart_vm=True)
    k8s = FakeK8s()
    with factory() as db:
        row = db.get(VMArchive, name)
        row.manifest = {**row.manifest, "disks": archives.disk_volumes(k8s.vm)}
        row.restore_data = {"switched": True}
        row.error = "previous error"
        db.commit()
    for i, volume in enumerate(k8s.vm["spec"]["template"]["spec"]["volumes"][:2]):
        volume.pop("persistentVolumeClaim", None)
        volume["dataVolume"] = {"name": f"restore-1-disk-{i}"}
    return name, k8s


def test_finish_recovers_old_false_failure_only_after_verified_switch(db_env, monkeypatch):
    from app.core.k8s_client import K8sClient
    factory, _s3 = db_env
    name, k8s = completed_restore(factory, restore_state="Failed")
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    # Реальный парсер воспроизводит ВМ после start: runStrategy=Always,
    # нет старого spec.running, VMI уже Running.
    k8s.vm["metadata"]["namespace"] = "default"
    k8s.vm["spec"].pop("running")
    k8s.vm["spec"]["runStrategy"] = "Always"
    parser = K8sClient.__new__(K8sClient)
    parser.core_api = NS(
        read_namespaced_secret=lambda *args: NS(data={"password": "eA=="}),
        list_namespaced_pod=lambda **kwargs: NS(items=[]),
    )
    monkeypatch.setattr("app.db.SessionLocal", factory)
    k8s.get_vm = lambda name: parser._parse_vm_object(
        k8s.vm, {"metadata": {}, "status": {"phase": "Running"}})
    with factory() as db:
        row = db.get(VMArchive, name)
        archives._finish(db, k8s, row)
        assert row.restore_state is None
        assert row.operation is None
        assert row.error is None
        assert row.status == "Succeeded"
    assert not any(action[0] in {"start", "delete"} for action in k8s.actions)
    assert ("unlock", "restore-1") in k8s.actions


@pytest.mark.parametrize("verified_switch", [False, True])
def test_recovery_does_not_claim_success_for_unconfirmed_or_changed_disks(db_env, monkeypatch, verified_switch):
    factory, _s3 = db_env
    name, k8s = completed_restore(factory, restore_state="Failed")
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    with factory() as db:
        row = db.get(VMArchive, name)
        row.restore_data = {"switched": verified_switch}
        if verified_switch:
            k8s.vm["spec"]["template"]["spec"]["volumes"][1]["dataVolume"]["name"] = "different-disk"
        archives._finish(db, k8s, row)
        assert row.restore_state == "Failed"
        assert row.error == "previous error"
    # Даже при настоящем сбое нельзя удалять подключённый импортный диск.
    assert ("delete", "restore-1-disk-0") not in k8s.actions


def test_recovery_never_finishes_restore_for_recreated_vm(db_env, monkeypatch):
    factory, _s3 = db_env
    name, k8s = completed_restore(factory, restore_state="Failed")
    k8s.vm["metadata"]["uid"] = "replacement-vm"
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    with factory() as db:
        row = db.get(VMArchive, name)
        archives._finish(db, k8s, row)
        assert row.status == "Failed"
        assert row.restore_state == "Failed"
    assert not any(action[0] in {"start", "unlock", "delete"} for action in k8s.actions)


def test_finish_waits_on_already_running_start_race_without_failing_restore(db_env, monkeypatch):
    factory, _s3 = db_env
    name, k8s = completed_restore(factory)
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    k8s.get_vm = lambda name: {"status": "Stopped"}
    def already_running(name):
        error = ApiException(status=409)
        error.body = json.dumps({"message": 'VM is already running'})
        raise error
    k8s.start_vm = already_running
    with factory() as db:
        row = db.get(VMArchive, name)
        archives._finish(db, k8s, row)
        assert row.restore_state == "Finalizing"
        assert row.operation == "restore-1"
        assert not any(action[0] == "unlock" for action in k8s.actions)
        k8s.get_vm = lambda name: {"status": "Running"}
        archives._finish(db, k8s, row)
        assert row.operation is None
        assert row.restore_state is None
        assert row.error is None


@pytest.mark.parametrize("status,message", [(409, "migration conflict"), (403, "VM is already running"),
                                             (500, "server error")])
def test_finish_does_not_swallow_unrelated_start_errors(db_env, monkeypatch, status, message):
    factory, _s3 = db_env
    name, k8s = completed_restore(factory)
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    k8s.get_vm = lambda name: {"status": "Stopped"}
    def fail(name):
        error = ApiException(status=status)
        error.body = json.dumps({"message": message})
        raise error
    k8s.start_vm = fail
    with factory() as db:
        with pytest.raises(ApiException):
            archives._finish(db, k8s, db.get(VMArchive, name))
    assert not any(action[0] == "unlock" for action in k8s.actions)


@pytest.mark.parametrize("restoring", [False, True])
def test_worker_retries_finalization_without_marking_completed_disks_failed(db_env, monkeypatch, restoring):
    factory, _s3 = db_env
    if restoring:
        name, k8s = completed_restore(factory)
    else:
        name = new_record(factory, status="Finalizing", operation="s3-backup-1")
        k8s = FakeK8s()
    class Guard:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, *args, **kwargs):
            return NS(scalar=lambda: True)
        def commit(self):
            pass
    monkeypatch.setattr("app.db.engine", NS(connect=Guard))
    original_finish = archives._finish
    def fail(*args):
        raise ApiException(status=503)
    monkeypatch.setattr(archives, "_finish", fail)
    archives.process_archives(k8s)
    with factory() as db:
        row = db.get(VMArchive, name)
        assert row.operation
        assert (row.restore_state if restoring else row.status) == "Finalizing"
    monkeypatch.setattr(archives, "_finish", original_finish)
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    archives.process_archives(k8s)
    with factory() as db:
        row = db.get(VMArchive, name)
        assert row.status == "Succeeded"
        assert row.restore_state is None
        assert row.operation is None
        assert row.error is None


def test_restore_does_not_switch_until_every_import_is_complete(db_env, monkeypatch):
    factory, _s3 = db_env
    name = new_record(factory)
    k8s = FakeK8s()
    monkeypatch.setattr(archives, "Minio", lambda *args, **kwargs: NS(presigned_get_object=lambda *a, **k: "http://signed-s3/disk.img"))
    monkeypatch.setenv("MINIO_ROOT_USER", "root")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")
    monkeypatch.setattr("app.api.vms.get_host_ip", lambda: "172.20.0.1")
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    with factory() as db:
        row = db.get(VMArchive, name)
        row.status = "Succeeded"
        row.operation = "restore-operation"
        row.restore_state = "Pending"
        row.manifest = {**row.manifest, "disks": [
            {**vol, "object": f"disk{i}", "claim": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}}}
            for i, vol in enumerate(row.manifest["volumes"])
        ]}
        db.commit()
        archives._restore(db, k8s, row)
        assert not k8s.patches
        assert archives.disk_volumes(k8s.vm)[0]["pvc"] == "root-pvc"
        k8s.dvs["restore-operation-disk-0"]["status"]["phase"] = "Succeeded"
        archives._restore(db, k8s, row)
        assert not k8s.patches
        k8s.dvs["restore-operation-disk-1"]["status"]["phase"] = "Succeeded"
        archives._restore(db, k8s, row)
        assert len(k8s.patches) == 1
        assert {v["pvc"] for v in archives.disk_volumes(k8s.vm)} == {
            "restore-operation-disk-0", "restore-operation-disk-1",
        }
        assert "dataVolumeTemplates" not in k8s.vm["spec"]


def test_retention_never_deletes_other_users_copies(db_env):
    factory, s3 = db_env
    new_record(factory)
    with factory() as db:
        row = db.get(VMArchive, "s3-backup-1")
        row.status = "Succeeded"
        row.retention = 1
        for i, owner in [(2, 1), (3, 2)]:
            old = VMArchive(name=f"old-{i}", vm_name="vm1", owner_id=owner, kind="backup", bucket=bucket_name(owner),
                            prefix=f"old-{i}/", status="Succeeded", created_at=datetime(2020, 1, i))
            db.add(old)
            s3.objects[(old.bucket, old.prefix + "disk.img")] = b"old"
        db.commit()
        archives._prune(db, row)
        assert db.get(VMArchive, "old-2") is None
        assert db.get(VMArchive, "old-3") is not None
    assert s3.removed == [(bucket_name(1), "old-2/disk.img")]


def test_failed_capture_resumes_power_recovery_after_new_session(db_env, monkeypatch):
    factory, _s3 = db_env
    name = new_record(factory)
    k8s = FakeK8s()
    k8s.stop_vm("vm1")
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    with factory() as db:
        row = db.get(VMArchive, name)
        row.status, row.operation, row.restart_vm = "Failed", name, True
        db.commit()
    with factory() as db:
        archives._finish(db, k8s, db.get(VMArchive, name))
    with factory() as db:
        row = db.get(VMArchive, name)
        assert row.operation == name
        archives._finish(db, k8s, row)
        assert row.operation is None and row.status == "Failed"
    assert ("start", "vm1") in k8s.actions


def test_cleanup_never_restarts_a_recreated_vm(db_env, monkeypatch):
    factory, _s3 = db_env
    name = new_record(factory)
    k8s = FakeK8s()
    k8s.vm["metadata"]["uid"] = "different-vm"
    monkeypatch.setattr(archives, "_delete_export", lambda *args: None)
    with factory() as db:
        row = db.get(VMArchive, name)
        row.operation, row.restart_vm = name, True
        archives._finish(db, k8s, row)
        assert row.operation is None
    assert not k8s.actions


def test_insufficient_minio_space_does_not_stop_guest(db_env, monkeypatch):
    factory, _s3 = db_env
    name = new_record(factory)
    k8s = FakeK8s()
    monkeypatch.setattr("app.core.capacity.host_totals", lambda: {"disk_free_gb": 1})
    with factory() as db:
        with pytest.raises(RuntimeError, match="места"):
            archives._capture(db, k8s, db.get(VMArchive, name))
    assert not any(action == "stop" for action, _ in k8s.actions)


def test_export_does_not_accept_external_or_plain_http_links():
    for url in ["http://export.default.svc/disk", "https://external.example/disk"]:
        with pytest.raises(RuntimeError, match="адрес"):
            archives._open_export(FakeK8s(), {"serviceName": "export"}, url, "secret")


def test_pending_restore_reserves_capacity_before_dv_exists(db_env):
    from app.core.capacity import known_storage_reservations_gb
    factory, _s3 = db_env
    name = new_record(factory)
    with factory() as db:
        row = db.get(VMArchive, name)
        row.operation, row.restore_state = "restore-new", "Pending"
        row.restore_data = {"reserved_gb": 10}
        db.commit()
        assert known_storage_reservations_gb(db) == 12  # 2 ГБ ВМ + 10 ГБ staging


def test_backup_bucket_keys_cannot_read_another_bucket_or_write(db_env, monkeypatch):
    from pathlib import Path
    from app.models.models import UserBucket
    from app.services import backup_storage as storage
    factory, s3 = db_env
    policies = []
    monkeypatch.setenv("MINIO_ROOT_USER", "root")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")
    def run(command, **kwargs):
        if "--policy" in command:
            policies.append(json.loads(Path(command[command.index("--policy") + 1]).read_text()))
        return NS(returncode=0)
    monkeypatch.setattr(storage.subprocess, "run", run)
    with factory() as db:
        db.connection().connection.driver_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 0)
        assert storage.ensure_backup_bucket(db, 1, s3) == bucket_name(1)
        db.commit()
        assert storage.ensure_backup_bucket(db, 1, s3) == bucket_name(1)
        assert len(policies) == 1
        assert db.query(UserBucket).one().purpose == "backup"
    statement = policies[0]["Statement"][0]
    assert set(statement["Action"]) == {"s3:GetBucketLocation", "s3:ListBucket", "s3:GetObject"}
    assert statement["Resource"] == ["arn:aws:s3:::aegis-backups-u1", "arn:aws:s3:::aegis-backups-u1/*"]


def test_mc_errors_do_not_expose_root_credentials(monkeypatch):
    import subprocess
    from app.services import backup_storage as storage
    command = ["mc", "alias", "set", "root-secret"]
    monkeypatch.setattr(storage.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(subprocess.CalledProcessError(1, command)))
    with pytest.raises(RuntimeError) as error:
        storage._run_mc(command)
    assert "root-secret" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("error_number", [2, 8, 13])
def test_unusable_mc_reports_rebuild_without_exposing_credentials(monkeypatch, error_number):
    from app.services import backup_storage as storage
    def fail(*args, **kwargs):
        raise OSError(error_number, "unusable executable", "root-secret")
    monkeypatch.setattr(storage.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="пересоберите") as error:
        storage._run_mc(["mc", "alias", "set", "root-secret"])
    assert "root-secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_backup_account_credentials_fit_minio_service_account_limits(db_env, monkeypatch):
    from app.core.crypto import decrypt_secret
    from app.models.models import UserBucket
    from app.services import backup_storage as storage
    factory, s3 = db_env
    accounts = []
    monkeypatch.setenv("MINIO_ROOT_USER", "root")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test-root-password")

    def run(command, **kwargs):
        if "--access-key" in command:
            access = command[command.index("--access-key") + 1]
            secret = command[command.index("--secret-key") + 1]
            # MinIO RELEASE.2025-09-07T16-13-09Z:
            # internal/auth/credentials.go, CreateNewCredentialsWithMetadata.
            assert 3 <= len(access) <= 20, "MinIO rejects this service-account Access Key"
            assert 8 <= len(secret) <= 40, "MinIO rejects this service-account Secret Key"
            accounts.append((access, secret))
        return NS(returncode=0)

    monkeypatch.setattr(storage.subprocess, "run", run)
    with factory() as db:
        db.connection().connection.driver_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 0)
        for owner in (1, 2):
            storage.ensure_backup_bucket(db, owner, s3)
        db.commit()
        for bucket, (access, secret) in zip(db.query(UserBucket).order_by(UserBucket.owner_id).all(), accounts):
            assert bucket.access_key == access
            assert decrypt_secret(bucket.secret_key) == secret
            assert bucket.secret_key != secret
    assert len(accounts) == 2
    assert accounts[0][0] != accounts[1][0]
    assert accounts[0][1] != accounts[1][1]


def test_legacy_database_dumps_do_not_leak_a_previous_database():
    from app.services.backup_storage import _legacy_owned
    db = NS(created_at=datetime(2026, 10, 8))
    assert not _legacy_owned(db, NS(last_modified=datetime(2026, 10, 7, tzinfo=timezone.utc)))
    assert _legacy_owned(db, NS(last_modified=datetime(2026, 10, 9, tzinfo=timezone.utc)))
