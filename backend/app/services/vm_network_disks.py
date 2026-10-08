"""Preflight checks for PVCs selected in the VM creation form."""
from fastapi import HTTPException
from kubernetes.client.rest import ApiException

from app.models.models import UserVolume, VMTask


def validate_network_disks(db, client, user, requests):
    reservations = {}
    selected = set()
    for req in requests:
        rows = []
        for name in (req.network_drives or "").split(","):
            name = name.strip()
            if not name or ":/" in name:
                continue
            if name in selected:
                raise HTTPException(400, "Один PVC нельзя подключить сразу к нескольким создаваемым ВМ.")
            selected.add(name)
            row = db.query(UserVolume).filter(UserVolume.name == name).with_for_update().first()
            if row is None or (user.role != "admin" and row.owner_id != user.id):
                raise HTTPException(400, "Сетевой диск не найден или недоступен. Укажите точное имя своего PVC из раздела «Сетевые диски».")
            if row.attached_vm_id is not None or row.status != "Available":
                raise HTTPException(400, f"Диск {name} уже подключён или занят другой операцией.")
            # Before provisioning, the task is the reservation. Afterwards,
            # manifests are authoritative: network_drives is historical input
            # and can still reference a disk that has since been detached.
            for task in db.query(VMTask).filter(VMTask.status.in_(("Pending", "Provisioning"))).all():
                if name in [value.strip() for value in (task.network_drives or "").split(",")]:
                    raise HTTPException(400, f"Диск {name} уже выбран для другой ВМ. Сначала отключите его.")
            try:
                pvc = client.core_api.read_namespaced_persistent_volume_claim(name, "default")
                if pvc.metadata.deletion_timestamp or pvc.status.phase == "Lost":
                    raise HTTPException(400, f"Диск {name} удаляется или потерян; выберите другой PVC.")
                # VM manifests created via this same form were not historically
                # reflected in UserVolume.attached_vm_id. Check actual consumers.
                for plural in ("virtualmachines", "virtualmachineinstances"):
                    items = client.custom_api.list_namespaced_custom_object(
                        "kubevirt.io", "v1", "default", plural).get("items", [])
                    for vm in items:
                        spec = vm.get("spec", {})
                        volumes = spec.get("template", {}).get("spec", spec).get("volumes", [])
                        if any(vol.get("persistentVolumeClaim", {}).get("claimName") == name or
                               vol.get("dataVolume", {}).get("name") == name for vol in volumes):
                            raise HTTPException(400, f"Диск {name} уже используется другой ВМ. Сначала отключите его.")
            except ApiException as error:
                if error.status == 404:
                    raise HTTPException(400, f"PVC {name} отсутствует в кластере.") from None
                raise HTTPException(503, "Не удалось проверить доступность PVC; повторите позже.") from None
            rows.append(row)
        reservations[req.name] = rows
    return reservations
