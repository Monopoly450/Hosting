"""Installer network recovery without running root operations or downloading files."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "manifests" / "installer"
PLUGINS = ("bridge", "host-local", "loopback", "portmap")


def _source():
    return (ROOT / "install.sh").read_text()


def _executable(path, content="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def _run_cni(tmp_path, apt_status=0):
    source = _source()
    function = source[source.index("ensure_cni_plugins() {"):]
    function = function[:function.index('\nlog "Проверка CNI-плагинов')]
    trace = tmp_path / "apt-called"
    # All destination and package paths are temporary; apt is stubbed.
    script = f"""
set -e
log() {{ :; }}
error() {{ echo "$1" >&2; exit 1; }}
apt-get() {{ touch {shlex.quote(str(trace))}; return {apt_status}; }}
{function}
ensure_cni_plugins "$CNI_DEST" "$CNI_BUNDLED" "$CNI_PACKAGE"
"""
    env = dict(os.environ, CNI_DEST=str(tmp_path / "cni"),
               CNI_BUNDLED=str(tmp_path / "bundled"),
               CNI_PACKAGE=str(tmp_path / "package"))
    result = subprocess.run(["bash", "-c", script], env=env,
                            capture_output=True, text=True)
    return result, trace


def test_existing_cni_plugins_are_kept_without_network(tmp_path):
    for plugin in PLUGINS:
        _executable(tmp_path / "cni" / plugin, "#!/bin/sh\n# existing custom plugin\n")
    result, trace = _run_cni(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not trace.exists()
    assert "existing custom plugin" in (tmp_path / "cni" / "bridge").read_text()


def test_bundled_k3s_plugins_repair_missing_or_broken_links(tmp_path):
    for plugin in PLUGINS:
        _executable(tmp_path / "bundled" / plugin)
    (tmp_path / "cni").mkdir()
    (tmp_path / "cni" / "bridge").symlink_to(tmp_path / "missing")
    result, trace = _run_cni(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not trace.exists()
    for plugin in PLUGINS:
        assert (tmp_path / "cni" / plugin).resolve() == tmp_path / "bundled" / plugin
        assert os.access(tmp_path / "cni" / plugin, os.X_OK)


def test_ubuntu_package_fills_only_missing_plugins(tmp_path):
    _executable(tmp_path / "cni" / "bridge", "#!/bin/sh\n# existing custom plugin\n")
    for plugin in PLUGINS:
        _executable(tmp_path / "package" / plugin)
    result, trace = _run_cni(tmp_path)
    assert result.returncode == 0, result.stderr
    assert trace.exists()
    assert "existing custom plugin" in (tmp_path / "cni" / "bridge").read_text()
    for plugin in PLUGINS:
        assert os.access(tmp_path / "cni" / plugin, os.X_OK)


@pytest.mark.parametrize("apt_status", [0, 1])
def test_missing_cni_plugins_stop_installation(tmp_path, apt_status):
    result, trace = _run_cni(tmp_path, apt_status)
    assert trace.exists()
    assert result.returncode != 0
    assert "CNI" in result.stderr


def test_vendored_manifests_match_checksums_and_parse_as_kubernetes_objects():
    sources = json.loads((MANIFESTS / "sources.json").read_text())
    checksums = {}
    for line in (MANIFESTS / "SHA256SUMS").read_text().splitlines():
        checksum, filename = line.split()
        checksums[filename] = checksum
        assert hashlib.sha256((MANIFESTS / filename).read_bytes()).hexdigest() == checksum
    assert "sources.json" in checksums
    for record in sources["files"]:
        assert checksums[record["file"]] == record["sha256"]
        objects = list(yaml.safe_load_all((MANIFESTS / record["file"]).read_text()))
        assert objects and all(obj.get("apiVersion") and obj.get("kind") for obj in objects)


@pytest.mark.parametrize("cni_dir", ["/var/lib/rancher/k3s/data/cni",
                                    "/var/lib/rancher/k3s/data/current/bin"])
def test_multus_patching_preserves_json_and_host_mounts(tmp_path, cni_dir):
    source = _source()
    start = source.index('cat "$MANIFEST_DIR/multus-daemonset-thick.yml"')
    command = source[start:source.index('\n\n[ -s /tmp/multus-k3s.yml', start)]
    output = tmp_path / "multus.yaml"
    command = command.replace("/tmp/multus-k3s.yml", shlex.quote(str(output)))
    sources = json.loads((MANIFESTS / "sources.json").read_text())
    conf_dir = "/var/lib/rancher/k3s/agent/etc/cni/net.d"
    env = dict(os.environ, MANIFEST_DIR=str(MANIFESTS), CNI_BIN_DIR=cni_dir,
               CNI_CONF_DIR=conf_dir, MULTUS_IMAGE=sources["multus_image"])
    subprocess.run(["bash", "-c", "set -eo pipefail\n" + command], env=env, check=True)
    objects = list(yaml.safe_load_all(output.read_text()))
    configmap = next(obj for obj in objects if obj["kind"] == "ConfigMap")
    config = json.loads(configmap["data"]["daemon-config.json"])
    assert config["binDir"] == cni_dir
    assert config["cniConfigDir"] == "/host" + conf_dir
    daemon = next(obj for obj in objects if obj["kind"] == "DaemonSet")
    pod = daemon["spec"]["template"]["spec"]
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    assert volumes["cnibin"]["hostPath"]["path"] == "/var/lib/rancher/k3s/data"
    assert volumes["cni"]["hostPath"]["path"] == conf_dir
    for container in pod["containers"] + pod["initContainers"]:
        assert container["image"] == sources["multus_image"]
        for mount in container["volumeMounts"]:
            assert mount["name"] in volumes
            if mount["name"] == "multus-daemon-config":
                assert mount["mountPath"] == "/etc/cni/net.d/multus.d"
    init = pod["initContainers"][0]
    assert "/host" + cni_dir in init["command"]
    assert any(m["mountPath"] == "/host/var/lib/rancher/k3s/data"
               for m in init["volumeMounts"])
