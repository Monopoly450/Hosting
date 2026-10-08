import json
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import vms
from app.models.models import VMTask
from test_s3_archives import db_env
from test_vm_ssh_access import ssh_env
from test_vm_creation_inputs import creation_api


def legacy_ports(base=10):
    return vms.default_ports_for(base, "ubuntu")


def test_new_proxmox_has_https_8006_not_http_80():
    ports = vms.default_ports_for(10, "proxmox")
    assert {p["int_port"]: p["ext_port"] for p in ports} == {22: 22010, 8006: 28010}
    assert vms.resolve_vm_ports("10.42.0.5", 10, None, "proxmox") == ports


def test_creation_api_persists_proxmox_management_forward(creation_api):
    api, factory, _, queue = creation_api
    response = api.post("/vms", json={"name": "proxmox-new", "os_type": "proxmox"})
    assert response.status_code == 201, response.text
    with factory() as db:
        task = db.query(VMTask).filter(VMTask.name == "proxmox-new").one()
        assert json.loads(task.ports_config) == vms.default_ports_for(task.id, "proxmox")
    queue.assert_called_once()


def test_proxmox_clone_gets_its_own_management_port(ssh_env, monkeypatch):
    factory, _, _, _ = ssh_env
    with factory() as db:
        db.query(VMTask).one().os_type = "proxmox"
        db.commit()
    queue = MagicMock()
    monkeypatch.setattr("app.queue_client.publish_task", queue)
    monkeypatch.setattr("shutil.disk_usage", lambda _: (100 * 1024**3, 0, 100 * 1024**3))
    result = vms.clone_vm("vm1", vms.VMCloneRequest(new_name="proxmox-clone"), NS(id=1, role="admin"))
    with factory() as db:
        clone = db.query(VMTask).filter(VMTask.name == "proxmox-clone").one()
        assert json.loads(clone.ports_config) == vms.default_ports_for(clone.id, "proxmox")
        assert result["task_id"] == clone.id
    queue.assert_called_once()


def test_legacy_standard_rule_is_repaired_and_repair_is_idempotent():
    before = legacy_ports()
    encoded = json.dumps(before)
    after = vms.resolve_vm_ports("10.42.0.5", 10, encoded, "proxmox")
    assert after[1] == {"ext_port": 28010, "int_port": 8006, "name": "Proxmox HTTPS"}
    assert after[0] == before[0] and after[2] == before[2]
    assert json.loads(encoded) == before
    assert vms.resolve_vm_ports("10.42.0.6", 10, json.dumps(after), "proxmox") == after
    assert vms.resolve_vm_ports("10.42.0.5", 10, encoded, "ubuntu") == before


@pytest.mark.parametrize("custom", [
    {"ext_port": 29010, "int_port": 80, "name": "HTTP"},
    {"ext_port": 28010, "int_port": 80, "name": "Custom web"},
    {"ext_port": 28010, "int_port": 8080, "name": "HTTP"},
    {"ext_port": 28010, "int_port": 80, "name": "HTTP", "protocol": "udp"},
])
def test_custom_rules_are_not_overwritten(custom):
    assert vms.resolve_vm_ports("10.42.0.5", 10, json.dumps([custom]), "proxmox") == [custom]


def test_existing_manual_proxmox_rule_is_not_duplicated():
    before = [*legacy_ports(), {"ext_port": 30010, "int_port": 8006, "name": "PVE"}]
    assert vms.resolve_vm_ports("10.42.0.5", 10, json.dumps(before), "proxmox") == before


def test_migration_preserves_internal_and_external_allowlists():
    before = json.dumps(legacy_ports())
    after = vms.resolve_vm_ports("10.42.0.5", 10, before, "proxmox")
    rules = [{"port": 80, "allowed_ips": ["192.0.2.5/32"]},
             {"port": 28010, "allowed_ips": ["192.0.2.6/32"]}]
    effective = vms.effective_firewall_rules(before, json.dumps(rules), after)
    assert effective == [*rules, {"port": 8006, "allowed_ips": ["192.0.2.5/32"]}]
    explicit = [*rules, {"port": 8006, "allowed_ips": ["192.0.2.7/32"]}]
    assert vms.effective_firewall_rules(before, json.dumps(explicit), after) == explicit


def test_reconcile_and_watchdog_use_corrected_target_and_preserve_restriction(ssh_env, monkeypatch):
    _, _, _, _ = ssh_env
    run = MagicMock(return_value=NS(returncode=0, stdout=""))
    monkeypatch.setattr("subprocess.run", run)
    encoded = json.dumps(legacy_ports())
    vms.reconcile_vm_firewall_rules("10.42.0.5", 10, encoded,
        json.dumps([{"port": 80, "allowed_ips": ["192.0.2.5/32"]}]), "proxmox")
    commands = [call.args[0][-1] for call in run.call_args_list]
    assert "iptables -t nat -A PREROUTING -p tcp --dport 28010 -j DNAT --to-destination 10.42.0.5:8006" in commands
    assert "iptables -A FORWARD -p tcp -s 192.0.2.5/32 -d 10.42.0.5 --dport 8006 -j ACCEPT" in commands
    assert "iptables -A FORWARD -p tcp -d 10.42.0.5 --dport 8006 -j DROP" in commands
    ports = vms.resolve_vm_ports("10.42.0.5", 10, encoded, "proxmox")
    old_dnat = '\n'.join(f'-A PREROUTING -p tcp --dport {p["ext_port"]} -j DNAT --to-destination 10.42.0.5:{p["int_port"]}' for p in legacy_ports())
    assert not vms.dnat_rules_present(old_dnat, "10.42.0.5", ports)
    assert vms.dnat_rules_present(old_dnat.replace(":80", ":8006"), "10.42.0.5", ports)


def test_details_show_same_ports_and_probe_8006_not_80(ssh_env, monkeypatch):
    factory, k8s, _, inspector = ssh_env
    before = json.dumps(legacy_ports(1))
    with factory() as db:
        task = db.query(VMTask).one()
        task.os_type = "proxmox"
        task.ports_config = before
        task.firewall_rules = '[{"port":80,"allowed_ips":["192.0.2.5/32"]}]'
        db.commit()
    k8s.get_vm.return_value.update(os_type="proxmox", ips=["10.42.0.5"], http_port=28001, https_port=44301)
    reconcile = MagicMock()
    monkeypatch.setattr(vms, "reconcile_vm_firewall_rules", reconcile)
    probe = MagicMock(return_value=True)
    monkeypatch.setattr("app.core.netutils.port_is_open", probe)
    result = vms.get_vm_details("vm1", k8s, NS(id=1, role="admin"))
    assert result["ports_config"][1]["int_port"] == 8006
    assert result["proxmox_port"] == 28001
    assert result["proxmox_available"] is True
    assert result["http_port"] is result["https_port"] is None
    assert result["ssh_access"]["web_terminal_enabled"] is False
    assert {"port": 8006, "allowed_ips": ["192.0.2.5/32"]} in result["firewall_rules"]
    probe.assert_called_once_with("10.42.0.5", 8006)
    reconcile.assert_called_once()
    inspector.assert_not_called()
    with factory() as db:
        assert db.query(VMTask).one().ports_config == before


@pytest.mark.parametrize("endpoint", ["metrics", "execute"])
def test_proxmox_rest_terminal_never_attempts_password_ssh(ssh_env, endpoint):
    factory, k8s, ssh_factory, inspector = ssh_env
    with factory() as db:
        db.query(VMTask).one().os_type = "proxmox"
        db.commit()
    with pytest.raises(HTTPException) as exc:
        if endpoint == "metrics":
            vms.get_vm_ssh_details("vm1", k8s, NS(id=1, role="admin"))
        else:
            vms.execute_vm_ssh_command("vm1", vms.VMCommandExecuteRequest(command="hostname"), k8s, NS(id=1, role="admin"))
    assert exc.value.status_code == 409
    inspector.assert_not_called()
    ssh_factory.assert_not_called()
