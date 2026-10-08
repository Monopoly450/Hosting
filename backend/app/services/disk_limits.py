"""Снятие дисковых ограничений, оставшихся от прежней версии панели."""
import logging
import os
import subprocess
import uuid
from kubernetes.client.rest import ApiException
from sqlalchemy import or_

from ..models.models import VMTask

logger = logging.getLogger(__name__)
LEGACY_LIMIT_FIELDS = ("disk_read_mbs", "disk_write_mbs", "disk_read_iops", "disk_write_iops")


def clear_legacy_disk_limits(k8s, session_factory):
    # Поля оставлены ради совместимости БД. Ненулевое значение служит
    # маркером: обнуляем его только после успешного снятия runtime-лимита.
    with session_factory() as db:
        pending = db.query(VMTask.id, VMTask.name).filter(
            or_(*(getattr(VMTask, field) != 0 for field in LEGACY_LIMIT_FIELDS))).all()
    cleared = 0
    for vm_id, name in pending:
        try:
            # Ни при каких условиях не передаём прежние значения: только max.
            if not apply_vm_disk_limits(k8s, {"name": name}):
                continue
            with session_factory() as db:
                db.query(VMTask).filter(VMTask.id == vm_id, VMTask.name == name).update(
                    {field: 0 for field in LEGACY_LIMIT_FIELDS}, synchronize_session=False)
                db.commit()
            cleared += 1
            logger.info("Прежние ограничения скорости диска сняты для ВМ %s", name)
        except Exception:
            logger.exception("Не удалось снять прежние дисковые ограничения ВМ %s; повторим позже", name)
    return cleared


def _host(script, *args):
    # Аргументы передаются отдельно от shell-кода: имена PVC/пути не команды.
    command = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid",
               "sh", "-c", script, "disk-limits", *args]
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        raise RuntimeError(f"Не удалось применить дисковый I/O на хосте (код {error.returncode}): {detail}") from None


def _whole_device(major, minor):
    # io.max не принимает разделы: для /dev/sda1 нужен dev родителя sda.
    value = _host('device="$1"; base="/sys/dev/block/$device"; '
                  'if [ -f "$base/partition" ]; then '
                  'resolved=$(readlink -f "$base") || exit 1; '
                  'cat "${resolved%/*}/dev"; else printf "%s" "$device"; fi',
                  f"{major}:{minor}")
    parsed = value.split(":")
    if len(parsed) != 2 or not all(part.isdigit() for part in parsed) or int(parsed[0]) <= 0:
        raise RuntimeError("Некорректное блочное устройство для ограничения I/O")
    return value


def _devices(k8s, vm, pod_uid):
    template = vm.get("spec", {}).get("template", {}).get("spec", {})
    disk_names = {disk["name"] for disk in template.get("domain", {}).get("devices", {}).get("disks", [])
                  if "disk" in disk or "lun" in disk}
    devices = set()
    for volume in template.get("volumes", []):
        if volume.get("name") not in disk_names:
            continue
        name = volume.get("dataVolume", {}).get("name") or volume.get("persistentVolumeClaim", {}).get("claimName")
        if not name:
            continue
        pvc = k8s.core_api.read_namespaced_persistent_volume_claim(name, "default")
        if not pvc.spec.volume_name:
            raise RuntimeError(f"Диск {name} ещё не подключён к PV")
        pv = k8s.core_api.read_persistent_volume(pvc.spec.volume_name)
        host_path = getattr(pv.spec, "host_path", None) or getattr(pv.spec, "local", None)
        paths = []
        block = pvc.spec.volume_mode == "Block"
        if host_path and not block:
            paths.append(host_path.path)
        # CSI-диск: берём реальное устройство его mount, не общий диск k3s.
        for root in ("/var/lib/kubelet", "/var/lib/rancher/k3s/agent/kubelet"):
            if block:
                paths.append(f"{root}/pods/{pod_uid}/volumeDevices/kubernetes.io~csi/{pvc.spec.volume_name}")
            else:
                paths.append(f"{root}/pods/{pod_uid}/volumes/kubernetes.io~csi/{pvc.spec.volume_name}/mount")
        if any(not path.startswith("/") for path in paths):
            raise RuntimeError("Некорректный путь диска для ограничения I/O")
        fmt = "%t:%T" if block else "%d"
        result = _host('fmt="$1"; shift; for path do '
                       'if [ -e "$path" ]; then stat -Lc "$fmt" -- "$path"; exit $?; fi; '
                       'done; exit 1', fmt, *paths)
        if block:
            major, minor = (int(part, 16) for part in result.split(":"))
        else:
            device_id = int(result)
            major, minor = os.major(device_id), os.minor(device_id)
        if major == 0:
            raise RuntimeError(f"Хранилище диска {name} не поддерживает блочный cgroup I/O")
        devices.add(_whole_device(major, minor))
    if not devices:
        raise RuntimeError("Не найдены постоянные диски для ограничения I/O")
    return sorted(devices)


def apply_vm_disk_limits(k8s, settings):
    try:
        vmi = k8s.custom_api.get_namespaced_custom_object(
            "kubevirt.io", "v1", "default", "virtualmachineinstances", settings["name"])
    except ApiException as error:
        if error.status == 404:
            return False  # выключенная ВМ: применим при запуске
        raise
    if vmi.get("status", {}).get("phase") != "Running" or vmi.get("metadata", {}).get("deletionTimestamp"):
        return False
    vmi_uid = vmi["metadata"]["uid"]
    pods = k8s.core_api.list_namespaced_pod(
        namespace="default", label_selector=f"kubevirt.io/created-by={vmi_uid}").items
    pods = [pod for pod in pods if pod.status.phase == "Running" and not pod.metadata.deletion_timestamp]
    if not pods:
        return False
    vm = k8s.custom_api.get_namespaced_custom_object(
        "kubevirt.io", "v1", "default", "virtualmachines", settings["name"])
    limits = []
    for key, field, multiplier in (("disk_read_mbs", "rbps", 1024 ** 2),
                                    ("disk_write_mbs", "wbps", 1024 ** 2),
                                    ("disk_read_iops", "riops", 1),
                                    ("disk_write_iops", "wiops", 1)):
        value = int(settings.get(key) or 0)
        if value < 0:
            raise ValueError("Дисковые лимиты не могут быть отрицательными")
        limits.append(f"{field}={value * multiplier if value else 'max'}")
    for pod in pods:
        pod_uid = str(uuid.UUID(pod.metadata.uid))
        systemd_uid = pod_uid.replace("-", "_")
        groups = _host('find /sys/fs/cgroup -type d '
                       '\\( -name "$1" -o -name "$2" \\)',
                       f"*pod{systemd_uid}*.slice", f"pod{pod_uid}").splitlines()
        if not groups:
            raise RuntimeError("Не найден cgroup пода ВМ; проверьте cgroups v2 на хосте")
        devices = _devices(k8s, vm, pod_uid)
        for group in groups:
            if not group.startswith("/sys/fs/cgroup/") or "/../" in group:
                raise RuntimeError("Некорректный путь cgroup пода ВМ")
            for device in devices:
                # Ноль снимает прежний лимит; запись проверяется, ошибки не
                # игнорируются. Лимит родительского пода суммарный для compute.
                _host('test -f "$1/io.max" || { printf "io.max отсутствует: нужен cgroup v2 I/O controller\\n" >&2; exit 1; }; '
                      'printf "%s\\n" "$2" > "$1/io.max"',
                      group, device + " " + " ".join(limits))
    return True
