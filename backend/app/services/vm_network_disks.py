"""Preflight checks and connection state for managed network disks."""
from dataclasses import dataclass

from fastapi import HTTPException
from kubernetes.client.rest import ApiException

from app.models.models import UserVolume, VMTask


@dataclass(frozen=True)
class DiskConnection:
    vm_names: tuple[str, ...]
    status: str
    attachment_type: str
    volume_name: str | None = None

    @property
    def can_detach(self):
        return self.attachment_type == "hotplug" and self.volume_name is not None


def network_disk_connections(db, client, volumes):
    """Read VM/VMI manifests, including disks attached at creation time.

    Do not persist these derived connections in attached_vm_id: doing so would
    make the legacy VM-delete cascade delete previously independent disks.
    Historical network_drives input is only a reservation before provisioning,
    never proof that a running/stopped VM still has a disk attached.
    """
    if not volumes:
        return {}
    names = {volume.name for volume in volumes}
    consumers = {}

    def record(claim, vm_name, kind, volume_name=None):
        if claim not in names or not vm_name:
            return
        entries = consumers.setdefault(claim, {})
        previous = entries.get(vm_name)
        # A reservation must not override a real VM/VMI reference. If one
        # manifest describes a non-hotpluggable disk, don't allow hot-unplug.
        if previous and (kind == "reserved" or previous[0] == "creation"):
            return
        entries[vm_name] = (kind, volume_name)

    try:
        for plural in ("virtualmachines", "virtualmachineinstances"):
            items = client.custom_api.list_namespaced_custom_object(
                "kubevirt.io", "v1", "default", plural).get("items", [])
            for vm in items:
                vm_name = vm.get("metadata", {}).get("name")
                spec = vm.get("spec", {})
                template = spec.get("template", {}).get("spec", spec)
                for volume in template.get("volumes", []):
                    source = volume.get("persistentVolumeClaim") or volume.get("dataVolume") or {}
                    claim = source.get("claimName") or source.get("name")
                    kind = "hotplug" if source.get("hotpluggable") is True else "creation"
                    record(claim, vm_name, kind, volume.get("name"))
                # The hotplug API returns before the controller updates the
                # template. An accepted request already reserves this PVC.
                for request in vm.get("status", {}).get("volumeRequests", []):
                    options = request.get("addVolumeOptions", {})
                    source = options.get("volumeSource", {})
                    claim = source.get("persistentVolumeClaim", {}).get("claimName") or source.get("dataVolume", {}).get("name")
                    record(claim, vm_name, "reserved")
    except Exception as error:
        raise HTTPException(503, "Не удалось проверить подключения сетевых дисков в Kubernetes. Повторите позже.") from error

    tasks = db.query(VMTask).all()
    by_id = {task.id: task for task in tasks}
    for task in tasks:
        if task.status in ("Pending", "Provisioning"):
            for name in (task.network_drives or "").split(","):
                record(name.strip(), task.name, "reserved")

    # Keep the existing hotplug state during the short controller delay after
    # addvolume. Actual manifest references always take precedence.
    for volume in volumes:
        task = by_id.get(volume.attached_vm_id)
        if volume.name not in consumers and volume.status == "Attached" and task:
            clean_name = volume.name.removeprefix(f"vol-{volume.owner_id}-")
            record(volume.name, task.name, "hotplug", clean_name)

    result = {}
    for claim, entries in consumers.items():
        vm_names = tuple(sorted(entries))
        kinds = {kind for kind, _ in entries.values()}
        state = "Reserved" if kinds == {"reserved"} else "Attached"
        if len(entries) == 1:
            kind, volume_name = next(iter(entries.values()))
        else:
            kind, volume_name = "multiple", None
        result[claim] = DiskConnection(vm_names, state, kind, volume_name)
    return result


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
