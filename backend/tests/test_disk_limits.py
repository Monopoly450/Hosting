import os
import subprocess
from types import SimpleNamespace as NS

import pytest
from kubernetes.client.rest import ApiException

from app.services import disk_limits as limits

POD_UID = "bbbbbbbb-2222-3333-4444-555555555555"
VMI_UID = "aaaaaaaa-2222-3333-4444-555555555555"
GROUP = "/sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod" + POD_UID.replace("-", "_") + ".slice"


@pytest.fixture
def env(monkeypatch):
    vm = {"spec": {"template": {"spec": {"domain": {"devices": {"disks": [
        {"name": "root", "disk": {}}, {"name": "iso", "cdrom": {}}]}},
        "volumes": [{"name": "root", "dataVolume": {"name": "restore-disk-0"}},
                    {"name": "iso", "dataVolume": {"name": "windows-iso"}}]}}}}
    pod = NS(metadata=NS(uid=POD_UID, deletion_timestamp=None), status=NS(phase="Running"))
    pvc = NS(spec=NS(volume_name="pvc-restored", volume_mode="Filesystem"))
    pv = NS(spec=NS(host_path=NS(path="/storage/restored"), local=None))
    selectors, claims, host_calls = [], [], []
    def get(group, version, namespace, plural, name):
        if plural == "virtualmachineinstances":
            return {"metadata": {"uid": VMI_UID}, "status": {"phase": "Running"}}
        return vm
    def pods(**kwargs):
        selectors.append(kwargs["label_selector"])
        return NS(items=[pod])
    def read_pvc(name, namespace):
        claims.append(name)
        return pvc
    k8s = NS(custom_api=NS(get_namespaced_custom_object=get), core_api=NS(
        list_namespaced_pod=pods, read_namespaced_persistent_volume_claim=read_pvc,
        read_persistent_volume=lambda name: pv))
    def host(script, *args):
        # Проверяем реальные shell-скрипты, но не запускаем nsenter/запись.
        subprocess.run(["sh", "-n", "-c", script], check=True, capture_output=True)
        host_calls.append((script, args))
        if script.startswith("find"):
            return GROUP
        if script.startswith("fmt="):
            return str(os.makedev(8, 1000)) if args[0] == "%d" else "fd:1000"
        if script.startswith("device="):
            return args[0]
        return ""
    monkeypatch.setattr(limits, "_host", host)
    return NS(vm=vm, pod=pod, pvc=pvc, pv=pv, k8s=k8s, selectors=selectors, claims=claims, calls=host_calls, host=host)


def settings(**kwargs):
    return {"name": "vm1", "disk_read_mbs": 10, "disk_write_mbs": 20,
            "disk_read_iops": 100, "disk_write_iops": 200, **kwargs}


def writes(env):
    return [args for script, args in env.calls if script.startswith("test -f")]


def test_limits_use_actual_vmi_uid_restored_disk_and_full_device_number(env):
    assert limits.apply_vm_disk_limits(env.k8s, settings()) is True
    assert env.selectors == [f"kubevirt.io/created-by={VMI_UID}"]
    assert env.claims == ["restore-disk-0"]
    assert writes(env) == [(GROUP, "8:1000 rbps=10485760 wbps=20971520 riops=100 wiops=200")]
    assert "/storage/restored" in next(args for script, args in env.calls if script.startswith("fmt="))


def test_zero_limits_clear_previous_throttle_instead_of_skipping_vm(env):
    limits.apply_vm_disk_limits(env.k8s, settings())
    limits.apply_vm_disk_limits(env.k8s, settings(disk_read_mbs=0, disk_write_mbs=0, disk_read_iops=0, disk_write_iops=0))
    assert writes(env)[-1] == (GROUP, "8:1000 rbps=max wbps=max riops=max wiops=max")


def test_null_legacy_limits_are_treated_as_unlimited(env):
    limits.apply_vm_disk_limits(env.k8s, settings(disk_read_mbs=None, disk_write_mbs=None))
    assert "rbps=max wbps=max" in writes(env)[0][1]


def test_same_device_for_multiple_disks_gets_one_aggregate_limit(env):
    spec = env.vm["spec"]["template"]["spec"]
    spec["domain"]["devices"]["disks"].append({"name": "data", "disk": {}})
    spec["volumes"].append({"name": "data", "persistentVolumeClaim": {"claimName": "data-disk"}})
    limits.apply_vm_disk_limits(env.k8s, settings())
    assert env.claims == ["restore-disk-0", "data-disk"]
    assert len(writes(env)) == 1


def test_block_device_uses_rdev_not_filesystem_device(env):
    env.pvc.spec.volume_mode = "Block"
    limits.apply_vm_disk_limits(env.k8s, settings())
    assert writes(env)[0][1].startswith("253:4096 ")
    stat_args = next(args for script, args in env.calls if script.startswith("fmt="))
    assert stat_args[0] == "%t:%T"
    assert any("volumeDevices/kubernetes.io~csi/pvc-restored" in path for path in stat_args)


def test_csi_filesystem_uses_pod_mount_not_arbitrary_host_root(env):
    env.pv.spec.host_path = None
    limits.apply_vm_disk_limits(env.k8s, settings())
    stat_args = next(args for script, args in env.calls if script.startswith("fmt="))
    assert any(f"pods/{POD_UID}/volumes/kubernetes.io~csi/pvc-restored/mount" in path for path in stat_args)
    assert "/" not in stat_args


def test_partition_limits_are_applied_to_whole_device(env, monkeypatch):
    def host(script, *args):
        if script.startswith("device="):
            assert args == ("8:1000",)
            assert "/partition" in script
            return "8:0"
        return env.host(script, *args)
    monkeypatch.setattr(limits, "_host", host)
    limits.apply_vm_disk_limits(env.k8s, settings())
    assert writes(env)[0][1].startswith("8:0 ")


def test_stopped_vm_is_deferred_until_next_start(env):
    def stopped(*args):
        raise ApiException(status=404)
    env.k8s.custom_api.get_namespaced_custom_object = stopped
    assert limits.apply_vm_disk_limits(env.k8s, settings()) is False
    assert not env.calls


def test_deleting_pod_is_never_throttled(env):
    env.pod.metadata.deletion_timestamp = "2026-10-08T10:00:00Z"
    assert limits.apply_vm_disk_limits(env.k8s, settings()) is False
    assert not env.calls


@pytest.mark.parametrize("failure", ["no-cgroup", "no-device", "write-denied"])
def test_unapplied_limits_raise_error_instead_of_reporting_success(env, monkeypatch, failure):
    def host(script, *args):
        if failure == "no-cgroup" and script.startswith("find"):
            return ""
        if ((failure == "no-device" and script.startswith("fmt=")) or
                (failure == "write-denied" and script.startswith("test -f"))):
            raise subprocess.CalledProcessError(1, ["nsenter"])
        return env.host(script, *args)
    monkeypatch.setattr(limits, "_host", host)
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        limits.apply_vm_disk_limits(env.k8s, settings())


def test_unsafe_cgroup_path_is_rejected(env, monkeypatch):
    def host(script, *args):
        return "/tmp/unrelated" if script.startswith("find") else env.host(script, *args)
    monkeypatch.setattr(limits, "_host", host)
    with pytest.raises(RuntimeError, match="Некорректный путь cgroup"):
        limits.apply_vm_disk_limits(env.k8s, settings())
    assert not writes(env)


def test_host_command_checks_failure_and_does_not_interpolate_arguments(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return NS(stdout="ok\n")
    monkeypatch.setattr(limits.subprocess, "run", run)
    assert limits._host('printf "%s" "$1"', "/path/with 'quotes'; touch /tmp/no") == "ok"
    assert calls[0][1]["check"] is True
    assert calls[0][0][-1] == "/path/with 'quotes'; touch /tmp/no"
    assert "touch" not in calls[0][0][-3]


def test_host_command_failure_preserves_actionable_error(monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="io.max отсутствует: нужен cgroup v2 I/O controller")
    monkeypatch.setattr(limits.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="нужен cgroup v2 I/O controller"):
        limits._host('test -f "$1/io.max"', GROUP)
