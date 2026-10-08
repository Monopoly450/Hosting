import subprocess
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from kubernetes.client.rest import ApiException
from pydantic import ValidationError

from app.api import vms, clusters
from app.models.models import UserVolume, VMTask
from app.services import vm_inputs, vm_network_disks
from test_s3_archives import db_env


@pytest.fixture
def public_key():
    return Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


def request(**fields):
    return vms.VMCreationRequest(name="input-test", os_type="ubuntu", **fields)


def cloudinit(req):
    manifest = vms.generate_linux_manifest(req, "generated-password")
    volumes = manifest["spec"]["template"]["spec"]["volumes"]
    ci = next(v["cloudInitNoCloud"] for v in volumes if "cloudInitNoCloud" in v)
    return manifest, yaml.safe_load(ci["userData"]), ci


def test_all_fields_combine_and_russian_content_survives(public_key):
    req = request(packages="htop, curl, jq, htop", ssh_key=public_key + " русский комментарий",
                  network_drives="vol-1-test, nfs.example:/данные",
                  custom_user_data="""#cloud-config
timezone: Asia/Yekaterinburg
write_files:
  - path: /var/tmp/проверка.txt
    content: Привет, мир!
users:
  - name: ubuntu
    gecos: Тестовый пользователь
runcmd:
  - [sh, -c, 'printf "Готово\\n" > /var/tmp/result.txt']
""")
    manifest, doc, ci = cloudinit(req)
    assert req.packages == "htop, curl, jq"
    assert doc["ssh_pwauth"] is False
    ubuntu = next(u for u in doc["users"] if isinstance(u, dict) and u["name"] == "ubuntu")
    assert ubuntu["ssh_authorized_keys"] == [req.ssh_key]
    assert ubuntu["gecos"] == "Тестовый пользователь"
    assert len([u for u in doc["users"] if isinstance(u, dict) and u["name"] == "ubuntu"]) == 1
    assert any(f["content"] == "Привет, мир!" for f in doc["write_files"])
    assert doc["timezone"] == "Asia/Yekaterinburg"
    assert doc["runcmd"][0] == "set -e"
    assert any("htop curl jq" in cmd for cmd in doc["runcmd"] if isinstance(cmd, str))
    assert doc["runcmd"][-1][0:2] == ["sh", "-c"]
    assert any("qemu-guest-agent" in cmd for cmd in doc["runcmd"] if isinstance(cmd, str))
    assert doc["mounts"][0][0:2] == ["nfs.example:/данные", "/mnt/network_drive_1"]
    assert any(v.get("persistentVolumeClaim", {}).get("claimName") == "vol-1-test"
               for v in manifest["spec"]["template"]["spec"]["volumes"])
    assert yaml.safe_load(ci["networkData"])["ethernets"]


def test_custom_keys_do_not_remove_key_from_form(public_key):
    second = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    _, doc, _ = cloudinit(request(ssh_key=public_key, custom_user_data=
        f"#cloud-config\nusers:\n  - name: ubuntu\n    ssh_authorized_keys:\n      - {second}\n"))
    ubuntu = next(u for u in doc["users"] if isinstance(u, dict) and u["name"] == "ubuntu")
    assert ubuntu["ssh_authorized_keys"] == [public_key, second]


def test_custom_ssh_password_policy_is_respected_without_form_key():
    _, doc, _ = cloudinit(request(custom_user_data="#cloud-config\nssh_pwauth: false\n"))
    assert doc["ssh_pwauth"] is False
    assert not any("/PasswordAuthentication yes/'" in cmd or 'echo "PasswordAuthentication yes"' in cmd
                   for cmd in doc["runcmd"] if isinstance(cmd, str))


def test_explicit_custom_password_is_not_replaced_by_late_commands():
    _, doc, _ = cloudinit(request(custom_user_data="""#cloud-config
chpasswd:
  users:
    - name: ubuntu
      password: custom-test-password
      type: text
"""))
    assert not any(" | chpasswd" in cmd for cmd in doc["runcmd"] if isinstance(cmd, str))


def test_repeated_commands_run_twice_and_custom_file_overrides_same_path():
    base = "#cloud-config\nwrite_files:\n- path: /a\n  content: before\nruncmd:\n- echo base\n"
    custom = "#cloud-config\nwrite_files:\n- path: /a\n  content: после\nruncmd:\n- echo twice\n- echo twice\n"
    doc = yaml.safe_load(vm_inputs.merge_cloud_config(base, custom))
    assert doc["write_files"] == [{"path": "/a", "content": "после"}]
    assert doc["runcmd"] == ["echo base", "echo twice", "echo twice"]


def test_explicit_password_does_not_discard_custom_password_command():
    base = '#cloud-config\nruncmd:\n- echo "ubuntu:generated" | chpasswd\n'
    custom = '#cloud-config\npassword: custom\nruncmd:\n- echo "ubuntu:custom" | chpasswd\n'
    doc = yaml.safe_load(vm_inputs.merge_cloud_config(base, custom))
    assert doc["runcmd"] == ['echo "ubuntu:custom" | chpasswd']


@pytest.mark.parametrize("fields", [
    {"name": "сервер"}, {"name": "test vm"}, {"name": "-test"}, {"name": "test-"}, {"name": "a" * 64},
    {"os_type": "убунту"}, {"os_type": "nosuchos"},
    {"cpu_cores": "два"}, {"cpu_cores": 0}, {"cpu_cores": True}, {"memory_gb": 2.5}, {"disk_gb": 1},
    {"packages": "нгинкс"}, {"packages": "curl,,jq"}, {"packages": "curl;touch /tmp/pwn"},
    {"packages": "$(whoami)"}, {"packages": "--help"}, {"packages": "curl jq"},
    {"ssh_key": "публичный ключ"}, {"ssh_key": "ssh-ed25519 AAAA"},
    {"ssh_key": "-----BEGIN OPENSSH PRIVATE KEY-----"},
    {"network_drives": "диск"}, {"network_drives": "192.168.1.10"},
    {"network_drives": "999.999.1.1:/data"}, {"network_drives": "server:/data;touch /tmp/pwn"},
    {"network_drives": "vol-1-test,"}, {"network_drives": "мой-сервер:/share"},
    {"iso_url": "неправильная ссылка"}, {"iso_url": "file:///etc/passwd"},
    {"iso_url": "http://user:secret@host/image"},
    {"custom_user_data": "#cloud-config\nwrite_files: ["},
    {"custom_user_data": "#cloud-config\nпакеты: [curl]\n"},
    {"custom_user_data": "#cloud-config\npackagess: [curl]\n"},
    {"custom_user_data": "#cloud-config\nruncmd: echo hi\n"},
    {"custom_user_data": "#cloud-config\nruncmd:\n- echo привет: мир\n"},
    {"custom_user_data": "#cloud-config\nwrite_files:\n- content: missing path\n"},
    {"custom_user_data": "#cloud-config\npackages: [нгинкс]\n"},
    {"custom_user_data": "#cloud-config\nssh_pwauth: да\n"},
    {"custom_user_data": "#cloud-config\ntimezone: UTC\ntimezone: GMT\n"},
    {"custom_user_data": "#cloud-config\nruncmd: &a [*a]\n"},
    {"custom_user_data": "#!/bin/bash\necho test\n"},
    {"custom_user_data": "#cloud-config\n"},
    {"custom_user_data": "#cloud-config\ncloud_final_modules: []\n"},
    {"custom_user_data": "#cloud-config\ntimezone: Екатеринбург\n"},
    {"custom_user_data": "#cloud-config\nwrite_files:\n- path: relative/file\n  content: test\n"},
    {"custom_user_data": "#cloud-config\nusers: [{name: админ}]\n"},
    {"custom_user_data": "#cloud-config\nusers: [{name: ubuntu, ssh_authorized_keys: ['не ключ']}]\n"},
    {"os_type": "windows", "packages": "curl"},
    {"os_type": "custom"},
])
def test_invalid_inputs_fail_before_creation(fields):
    payload = {"name": "input-test", "os_type": "ubuntu", **fields}
    with pytest.raises(ValidationError):
        vms.VMCreationRequest(**payload)


def test_key_and_conflicting_password_auth_fail(public_key):
    with pytest.raises(ValidationError, match="несовместим"):
        request(ssh_key=public_key, custom_user_data="#cloud-config\nssh_pwauth: true\n")


def test_all_bad_fields_return_multiple_errors_and_api_has_no_side_effects(monkeypatch):
    app = FastAPI()
    app.include_router(vms.router, prefix="/vms")
    client = MagicMock()
    user = NS(id=1, role="admin")
    app.dependency_overrides[vms.get_k8s_client] = lambda: client
    app.dependency_overrides[vms.get_current_user] = lambda: user
    factory = MagicMock()
    monkeypatch.setattr("app.db.SessionLocal", factory)
    response = TestClient(app).post("/vms", json={"name": "русское имя", "os_type": "линукс",
        "packages": "пакет", "ssh_key": "не ключ", "network_drives": "диск", "cpu_cores": "два",
        "custom_user_data": "#cloud-config\nruncmd: ошибка\n"})
    assert response.status_code == 422
    assert len(response.json()["detail"]) >= 7
    factory.assert_not_called()
    assert not client.mock_calls


@pytest.fixture
def creation_api(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    from app.models.models import User
    # TestClient executes handlers in a separate thread; share a file-backed DB.
    engine = create_engine(f"sqlite:///{tmp_path / 'creation.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=1, username="one", password_hash="x"))
        db.add(VMTask(id=1, name="vm1", owner_id=1, os_type="ubuntu", cpu_cores=1, memory_gb=1, disk_gb=20))
        db.commit()
    from app.core import capacity, quotas, ratelimit
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr(capacity, "lock_host_capacity", lambda db: None)
    monkeypatch.setattr(capacity, "ensure_storage_capacity", lambda *args, **kwargs: None)
    monkeypatch.setattr(quotas, "enforce_quota", lambda *args, **kwargs: None)
    monkeypatch.setattr(ratelimit, "check_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(vms.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(vms.os, "sysconf", lambda key: 4096 if key == "SC_PAGE_SIZE" else 16 * 1024 ** 3 // 4096)
    queue = MagicMock(return_value=True)
    monkeypatch.setattr("app.queue_client.publish_task_or_fail_task", queue)
    app = FastAPI()
    app.include_router(vms.router, prefix="/vms")
    k8s = MagicMock()
    k8s.core_api.read_namespaced_persistent_volume_claim.return_value = NS(metadata=NS(deletion_timestamp=None), status=NS(phase="Bound"))
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": []}
    app.dependency_overrides[vms.get_k8s_client] = lambda: k8s
    app.dependency_overrides[vms.get_current_user] = lambda: NS(id=1, role="admin")
    with TestClient(app) as api:
        yield api, factory, k8s, queue
    engine.dispose()


def test_api_accepts_all_fields_and_queues_one_complete_task(creation_api, public_key):
    api, factory, k8s, queue = creation_api
    with factory() as db:
        db.add(UserVolume(name="vol-1-test", owner_id=1, size_gb=1, status="Available"))
        db.commit()
    response = api.post("/vms", json={"name": "combined-test", "os_type": "ubuntu", "packages": "htop, curl, jq",
        "ssh_key": public_key, "network_drives": "vol-1-test", "custom_user_data":
        "#cloud-config\nwrite_files:\n- path: /var/tmp/test.txt\n  content: Привет\nruncmd:\n- echo готово\n"})
    assert response.status_code == 201, response.text
    queue.assert_called_once()
    with factory() as db:
        task = db.query(VMTask).filter(VMTask.name == "combined-test").one()
        assert task.packages == "htop, curl, jq" and task.ssh_key == public_key
        assert task.network_drives == "vol-1-test" and "Привет" in task.custom_user_data
        # Selection itself must not introduce the VM-delete cascade for disks.
        assert db.query(UserVolume).one().attached_vm_id is None


def test_api_missing_pvc_does_not_create_or_queue_vm(creation_api):
    api, factory, k8s, queue = creation_api
    response = api.post("/vms", json={"name": "combined-test", "os_type": "ubuntu", "network_drives": "vol-1-missing"})
    assert response.status_code == 400
    queue.assert_not_called()
    with factory() as db:
        assert db.query(VMTask).count() == 1


def test_normalization_blank_fields_valid_unknown_package_and_cluster_inputs():
    req = vms.VMCreationRequest(name=" TEST-1 ", os_type=" Ubuntu ", ssh_key=" ",
                              custom_user_data="\n", packages="definitely-missing-test-package")
    assert req.name == "test-1" and req.ssh_key is None and req.custom_user_data is None
    assert req.packages == "definitely-missing-test-package"
    with pytest.raises(ValidationError):
        clusters.ClusterCreateRequest(name="test", vms=[req, req])
    with pytest.raises(ValidationError):
        clusters.ClusterCreateRequest(name="test", vms=[{"name": "vm", "os_type": "ubuntu", "packages": "пакет"}])


def test_runtime_install_failure_is_not_reported_as_success(monkeypatch):
    from app.services import os_profiles
    monkeypatch.setattr(os_profiles, "PACKAGE_INSTALL_RETRIES", 1)
    monkeypatch.setattr(os_profiles, "install_package_cmd_chain", lambda *args: "false")
    command = os_profiles.install_packages_runcmd("ubuntu", ["does-not-exist"])
    result = subprocess.run(["sh", "-c", "sleep() { :; }; " + command], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Не удалось установить" in result.stderr


def test_russian_command_name_fails_at_runtime_instead_of_silently_succeeding():
    _, doc, _ = cloudinit(request(custom_user_data="#cloud-config\nruncmd:\n- показать-систему\n"))
    assert doc["runcmd"][0] == "set -e"
    result = subprocess.run(["sh", "-c", "set -e; показать-систему; printf SUCCESS"], capture_output=True, text=True)
    assert result.returncode != 0 and "SUCCESS" not in result.stdout


@pytest.mark.parametrize("users", ["default", "{name: ubuntu, gecos: Русский комментарий}"])
def test_alternate_users_syntax_preserves_form_key(public_key, users):
    _, doc, _ = cloudinit(request(ssh_key=public_key, custom_user_data=f"#cloud-config\nusers: {users}\n"))
    assert any(isinstance(u, dict) and u.get("name") == "ubuntu" and public_key in u["ssh_authorized_keys"] for u in doc["users"])


def test_colon_in_ssh_comment_cannot_break_generated_yaml(public_key):
    key = public_key + " комментарий: тест"
    _, doc, _ = cloudinit(request(ssh_key=key))
    assert next(u for u in doc["users"] if isinstance(u, dict) and u["name"] == "ubuntu")["ssh_authorized_keys"] == [key]


@pytest.mark.parametrize("failure", ["missing", "other-owner", "attached", "absent-pvc", "unavailable-api", "live-vm", "deleting"])
def test_invalid_or_busy_pvc_is_rejected(db_env, failure):
    factory, _ = db_env
    k8s = MagicMock()
    k8s.core_api.read_namespaced_persistent_volume_claim.return_value = NS(metadata=NS(deletion_timestamp=None), status=NS(phase="Bound"))
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": []}
    with factory() as db:
        if failure != "missing":
            db.add(UserVolume(name="vol-1-test", owner_id=2 if failure == "other-owner" else 1,
                              size_gb=1, attached_vm_id=1 if failure == "attached" else None, status="Available"))
            db.commit()
        if failure in ("absent-pvc", "unavailable-api"):
            k8s.core_api.read_namespaced_persistent_volume_claim.side_effect = ApiException(status=404 if failure == "absent-pvc" else 500)
        if failure == "live-vm":
            k8s.custom_api.list_namespaced_custom_object.return_value = {"items": [{"spec": {"volumes": [
                {"persistentVolumeClaim": {"claimName": "vol-1-test"}}]}}]}
        if failure == "deleting":
            k8s.core_api.read_namespaced_persistent_volume_claim.return_value.metadata.deletion_timestamp = "now"
        with pytest.raises(HTTPException) as exc:
            vm_network_disks.validate_network_disks(db, k8s, NS(id=1, role="student"), [request(network_drives="vol-1-test")])
        assert exc.value.status_code == (503 if failure == "unavailable-api" else 400)
        assert db.query(UserVolume).filter(UserVolume.attached_vm_id.isnot(None)).count() == (1 if failure == "attached" else 0)


def test_pending_pvc_is_allowed_and_pending_vm_reference_prevents_reuse(db_env):
    factory, _ = db_env
    k8s = MagicMock()
    k8s.core_api.read_namespaced_persistent_volume_claim.return_value = NS(metadata=NS(deletion_timestamp=None), status=NS(phase="Pending"))
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": []}
    with factory() as db:
        row = UserVolume(name="vol-1-test", owner_id=1, size_gb=1, status="Available")
        db.add(row)
        db.flush()
        selected = vm_network_disks.validate_network_disks(db, k8s, NS(id=1, role="student"), [request(network_drives="vol-1-test")])
        assert selected["input-test"] == [row]
        db.query(VMTask).filter(VMTask.id == 1).one().network_drives = "vol-1-test"
        db.flush()
        assert row.attached_vm_id is None and row.status == "Available"
        with pytest.raises(HTTPException):
            vm_network_disks.validate_network_disks(db, k8s, NS(id=1, role="student"), [request(network_drives="vol-1-test")])


def test_detached_disk_can_be_reused_despite_historical_creation_input(db_env):
    factory, _ = db_env
    k8s = MagicMock()
    k8s.core_api.read_namespaced_persistent_volume_claim.return_value = NS(metadata=NS(deletion_timestamp=None), status=NS(phase="Bound"))
    k8s.custom_api.list_namespaced_custom_object.return_value = {"items": []}
    with factory() as db:
        db.add(UserVolume(name="vol-1-test", owner_id=1, size_gb=1, status="Available"))
        task = db.query(VMTask).one()
        task.status = "Running"
        task.network_drives = "vol-1-test"
        db.flush()
        assert vm_network_disks.validate_network_disks(db, k8s, NS(id=1, role="student"), [request(network_drives="vol-1-test")])
