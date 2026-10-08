#!/usr/bin/env bash
# Запускать на хосте K3s: включает VMExport, сохраняя прочие feature gates.
set -euo pipefail
python3 - <<'PY'
import copy
import json
import subprocess

command = ["kubectl", "-n", "kubevirt", "get", "kubevirt", "kubevirt", "-o", "json"]
vm = json.loads(subprocess.check_output(command))
configuration = copy.deepcopy(vm.get("spec", {}).get("configuration", {}))
developer = configuration.setdefault("developerConfiguration", {})
gates = developer.setdefault("featureGates", [])
if "VMExport" in gates:
    print("VMExport уже включён")
else:
    gates.append("VMExport")
    patch = [
        {"op": "test", "path": "/metadata/resourceVersion", "value": vm["metadata"]["resourceVersion"]},
        {"op": "add", "path": "/spec/configuration", "value": configuration},
    ]
    subprocess.run(["kubectl", "-n", "kubevirt", "patch", "kubevirt", "kubevirt",
                    "--type=json", "-p", json.dumps(patch)], check=True)
    print("VMExport включён; дождитесь готовности компонентов KubeVirt")
PY
