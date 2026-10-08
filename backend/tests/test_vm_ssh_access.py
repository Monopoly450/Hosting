import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import ssh_terminal, vms
from app.models.models import VMTask
from app.services import vm_ssh_access as access
from test_s3_archives import db_env


@pytest.mark.parametrize("os_type", ["ubuntu", "debian", "almalinux", "rocky", "fedora", "centos", "opensuse", "alpine", "arch", "custom"])
def test_own_key_disables_password_terminal_for_all_supported_os(os_type):
    task = NS(os_type=os_type, ssh_key="ssh-ed25519 test-public-key")
    assert access.ssh_access_policy(task) == {
        "auth_mode": "publickey", "web_terminal_enabled": False, "reason": "own_key"}


@pytest.mark.parametrize("os_type", ["windows", "truenas", "TrueNAS", "proxmox", "Proxmox"])
@pytest.mark.parametrize("key", [None, "ssh-ed25519 test-public-key"])
def test_iso_guests_do_not_offer_ssh_terminal(os_type, key):
    assert access.ssh_access_policy(NS(os_type=os_type, ssh_key=key))["reason"] == "unsupported_os"


def test_password_guests_keep_existing_terminal():
    assert access.ssh_access_policy(NS(os_type="ubuntu", ssh_key=None))["web_terminal_enabled"]
    assert not access.ssh_access_policy(os_type="proxmox")["web_terminal_enabled"]


def test_explicit_password_disable_in_yaml_also_stops_password_ssh():
    task = NS(os_type="debian", ssh_key=None, custom_user_data="#cloud-config\nssh_pwauth: false\n")
    assert access.ssh_access_policy(task)["reason"] == "password_disabled"
    task.custom_user_data = "#!/bin/sh\necho legacy script\n"
    assert access.ssh_access_policy(task)["web_terminal_enabled"]


@pytest.fixture
def ssh_env(db_env, monkeypatch):
    factory, _ = db_env
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr(vms, "check_vm_ownership", lambda *args, **kwargs: None)
    k8s = MagicMock()
    k8s.get_vm.return_value = {"name": "vm1", "os_type": "ubuntu", "status": "Running", "ips": [],
                               "credentials": {"username": "ubuntu", "password": "guest-password"}}
    k8s.query_prometheus.return_value = []
    monkeypatch.setattr(ssh_terminal, "K8sClient", lambda: k8s)
    ssh_factory = MagicMock()
    monkeypatch.setattr(ssh_terminal.paramiko, "SSHClient", ssh_factory)
    inspector = MagicMock()
    monkeypatch.setattr(vms, "SSHInspector", inspector)
    return factory, k8s, ssh_factory, inspector


def set_key(factory):
    with factory() as db:
        db.query(VMTask).one().ssh_key = "ssh-ed25519 test-public-key"
        db.commit()


def test_details_expose_policy_but_never_the_key(ssh_env):
    factory, k8s, _, _ = ssh_env
    set_key(factory)
    details = vms.get_vm_details("vm1", k8s, NS(id=1, role="admin"))
    assert details["ssh_access"]["auth_mode"] == "publickey"
    assert details["ssh_access"]["web_terminal_enabled"] is False
    assert "ssh_key" not in details
    assert "test-public-key" not in str(details)


def test_key_policy_survives_reload_and_does_not_mutate_vm(ssh_env):
    factory, k8s, _, _ = ssh_env
    set_key(factory)
    assert access.read_ssh_access("vm1")["reason"] == "own_key"
    assert access.read_ssh_access("vm1")["reason"] == "own_key"
    with factory() as db:
        assert db.query(VMTask).one().ssh_key == "ssh-ed25519 test-public-key"
    k8s.custom_api.patch_namespaced_custom_object.assert_not_called()


@pytest.mark.parametrize("endpoint", ["metrics", "execute"])
def test_rest_password_probes_are_rejected_without_attempting_ssh(ssh_env, endpoint):
    factory, k8s, ssh_factory, inspector = ssh_env
    set_key(factory)
    with pytest.raises(HTTPException) as exc:
        if endpoint == "metrics":
            vms.get_vm_ssh_details("vm1", k8s, NS(id=1, role="admin"))
        else:
            vms.execute_vm_ssh_command("vm1", vms.VMCommandExecuteRequest(command="hostname"), k8s, NS(id=1, role="admin"))
    assert exc.value.status_code == 409
    ssh_factory.assert_not_called()
    inspector.assert_not_called()


@pytest.mark.parametrize("mode", ["key", "windows", "truenas", "proxmox", "password-disabled"])
def test_websocket_is_closed_before_any_password_authentication(ssh_env, monkeypatch, mode):
    factory, k8s, ssh_factory, _ = ssh_env
    with factory() as db:
        task = db.query(VMTask).one()
        if mode == "key":
            task.ssh_key = "ssh-ed25519 test-public-key"
        elif mode == "password-disabled":
            task.custom_user_data = "#cloud-config\nssh_pwauth: false\n"
        else:
            task.os_type = mode
        db.commit()
    monkeypatch.setattr("app.core.auth.ADMIN_TOKEN", "ssh-test-token")
    ws = NS(accept=AsyncMock(), close=AsyncMock())
    asyncio.run(ssh_terminal.ssh_terminal_proxy(ws, "vm1", token="ssh-test-token"))
    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008, reason="Web SSH disabled; use your SSH key or VNC")
    ssh_factory.assert_not_called()


def test_unauthorized_socket_does_not_read_vm_policy_or_start_ssh(ssh_env):
    _, k8s, ssh_factory, _ = ssh_env
    ws = NS(accept=AsyncMock(), close=AsyncMock())
    asyncio.run(ssh_terminal.ssh_terminal_proxy(ws, "vm1", token=None))
    ws.close.assert_awaited_once_with(code=1008, reason="Unauthorized")
    k8s.get_vm.assert_not_called()
    ssh_factory.assert_not_called()


def test_existing_password_websocket_still_connects(ssh_env, monkeypatch):
    _, k8s, ssh_factory, _ = ssh_env
    k8s.get_vm.return_value["ips"] = ["172.20.0.38"]
    monkeypatch.setattr("app.core.auth.ADMIN_TOKEN", "ssh-test-token")
    monkeypatch.setattr(ssh_terminal, "ws_to_ssh_loop", AsyncMock())
    monkeypatch.setattr(ssh_terminal, "ssh_to_ws_loop", AsyncMock())
    ws = NS(accept=AsyncMock(), close=AsyncMock())
    asyncio.run(ssh_terminal.ssh_terminal_proxy(ws, "vm1", token="ssh-test-token"))
    ssh_factory.return_value.connect.assert_called_once_with(
        hostname="172.20.0.38", port=22, username="ubuntu", password="guest-password", timeout=10)
