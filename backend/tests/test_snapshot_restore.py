"""Откат на снимок при включённой ВМ."""
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException
from kubernetes.client.rest import ApiException

from app.api import snapshots as snapshot_api
from app.core.k8s_client import K8sClient


class FakeCustomApi:
    """Минимальный custom-objects API: помнит созданное и отдаёт заготовки."""

    def __init__(self, vmi_alive_calls=0, restores=None):
        self.vmi_alive_calls = vmi_alive_calls
        self.created = []
        self.patched = []
        self.restores = restores if restores is not None else {"items": []}

    def get_namespaced_custom_object(self, group, version, ns, plural, name):
        if plural == "virtualmachineinstances":
            if self.vmi_alive_calls > 0:
                self.vmi_alive_calls -= 1
                return {"metadata": {"name": name}}
            raise ApiException(status=404)
        raise ApiException(status=404)

    def create_namespaced_custom_object(self, group, version, ns, plural, body):
        self.created.append((plural, body))
        return body

    def list_namespaced_custom_object(self, group, version, ns, plural):
        return self.restores

    def patch_namespaced_custom_object(self, group, version, ns, plural, name, body):
        self.patched.append((name, body))
        return body


def _client(custom_api):
    c = K8sClient.__new__(K8sClient)
    c.custom_api = custom_api
    return c


def test_waiting_stops_as_soon_as_the_guest_is_gone():
    """Фиксированный sleep тут не годится: между stop_vm и исчезновением VMI
    проходит время выключения гостя — на HDD это десятки секунд. Слишком
    короткая пауза означает, что KubeVirt отклонит откат."""
    api = FakeCustomApi(vmi_alive_calls=2)
    slept = []
    c = _client(api)
    assert c.wait_for_vm_stopped("vm1", interval=0, timeout=30) is True


def test_waiting_gives_up_instead_of_hanging_forever():
    """ВМ может не погаснуть вовсе (зависший гость). Запрос обязан вернуть
    управление, а не держать соединение до таймаута прокси."""
    api = FakeCustomApi(vmi_alive_calls=10 ** 6)
    c = _client(api)
    assert c.wait_for_vm_stopped("vm1", interval=0, timeout=0.01) is False


def test_restore_marks_the_vm_for_restart_only_when_it_was_running():
    """Пометка живёт на объекте отката в кластере, а не в памяти процесса:
    откат идёт минутами, панель за это время может перезапуститься, и
    намерение пользователя потерялось бы вместе с ней — ВМ осталась бы
    выключенной без объяснений."""
    api = FakeCustomApi()
    c = _client(api)

    c.restore_vm_snapshot("vm1", "snap1", restart_after=True)
    plural, body = api.created[-1]
    assert plural == "virtualmachinerestores"
    assert body["metadata"]["annotations"][K8sClient.RESTART_AFTER_RESTORE] == "true"
    assert body["spec"]["targetReadinessPolicy"] == "StopTarget"

    c.restore_vm_snapshot("vm1", "snap1", restart_after=False)
    _, body = api.created[-1]
    assert body["metadata"]["annotations"] == {}, "выключенную ВМ включать не просили"


def test_only_finished_restores_are_picked_up_for_restart():
    """Запущенная посреди отката ВМ его сломает, поэтому ждём status.complete."""
    api = FakeCustomApi(restores={"items": [
        {"metadata": {"name": "r-done", "annotations": {K8sClient.RESTART_AFTER_RESTORE: "true"}},
         "spec": {"target": {"name": "vm-done"}}, "status": {"complete": True}},
        {"metadata": {"name": "r-busy", "annotations": {K8sClient.RESTART_AFTER_RESTORE: "true"}},
         "spec": {"target": {"name": "vm-busy"}}, "status": {"complete": False}},
        {"metadata": {"name": "r-manual", "annotations": {}},
         "spec": {"target": {"name": "vm-manual"}}, "status": {"complete": True}},
    ]})
    ready = _client(api).restores_awaiting_start()
    assert [r["vm"] for r in ready] == ["vm-done"]


def test_failed_restore_stops_blocking_after_restart_marker_is_cleared():
    restore = {
        "metadata": {"name": "r-failed", "annotations": {}},
        "spec": {"target": {"name": "vm1"}},
        "status": {
            "complete": False,
            "conditions": [{"type": "Failure", "status": "True"}],
        },
    }
    client = _client(FakeCustomApi(restores={"items": [restore]}))

    assert client.active_snapshot_restore("vm1") is None

    restore["metadata"]["annotations"] = {
        K8sClient.RESTART_AFTER_RESTORE: "true"
    }
    assert client.active_snapshot_restore("vm1") == "r-failed"


class SnapshotRestoreRouteClient:
    def __init__(self, vm=None, vm_error=None):
        self.vm = vm or {"status": "Starting", "desired_state": "Running"}
        self.vm_error = vm_error
        self.restart_after = None

    def ensure_no_backup_operation(self, _name):
        return None

    def list_vm_snapshots(self, _name):
        return [{
            "name": "snap-vm1-x", "phase": "Succeeded",
            "ready_to_use": True, "has_disk": True,
        }]

    def snapshot_support(self, _name):
        return {"supported": True}

    def get_vm(self, _name):
        if self.vm_error:
            raise self.vm_error
        return self.vm

    def acquire_vm_action_guard(self, *_args):
        return "guard"

    def restore_vm_snapshot(
        self, _vm, _snapshot, restart_after=False, restore_name=None,
    ):
        self.restart_after = restart_after

    def clear_vm_action_guard(self, *_args):
        return None


def test_snapshot_restore_preserves_desired_running_state(monkeypatch):
    monkeypatch.setattr(snapshot_api, "check_vm_ownership", lambda *_args: None)
    client = SnapshotRestoreRouteClient()

    snapshot_api.restore_snapshot("vm1", "snap-vm1-x", client, object())

    assert client.restart_after is True


def test_snapshot_restore_aborts_when_power_state_cannot_be_read(monkeypatch):
    monkeypatch.setattr(snapshot_api, "check_vm_ownership", lambda *_args: None)
    client = SnapshotRestoreRouteClient(vm_error=RuntimeError("read failed"))

    with pytest.raises(HTTPException) as exc:
        snapshot_api.restore_snapshot("vm1", "snap-vm1-x", client, object())

    assert exc.value.status_code == 500
    assert client.restart_after is None


def test_get_vm_exposes_snapshot_restore_operation_lock():
    class VmApi(FakeCustomApi):
        def get_namespaced_custom_object(self, *args, **kwargs):
            plural = kwargs.get("plural", args[3] if len(args) > 3 else None)
            name = kwargs.get("name", args[4] if len(args) > 4 else None)
            if plural == "virtualmachines":
                return {"metadata": {"name": name}}
            raise ApiException(status=404)

    client = _client(VmApi())
    client._parse_vm_object = lambda *_args: {"backup_operation": None}
    client.active_snapshot_restore = lambda *_args: "restore-snap-vm1-x"

    vm = client.get_vm("vm1")

    assert vm["backup_operation"] == "snapshot-restore:restore-snap-vm1-x"


def test_missing_snapshot_crd_is_not_an_error_for_the_worker():
    """На кластере без снимков CRD отката нет вовсе. Демон должен молчать, а
    не сыпать ошибками раз в 20 секунд."""
    class NoCrd(FakeCustomApi):
        def list_namespaced_custom_object(self, *a, **kw):
            raise ApiException(status=404)

    assert _client(NoCrd()).restores_awaiting_start() == []


def test_restart_mark_is_removed_after_the_vm_starts():
    """Оставленная аннотация означала бы, что следующий тик снова включит ВМ —
    и машина, которую после отката осознанно выключили, поднималась бы сама
    раз в 20 секунд."""
    api = FakeCustomApi()
    _client(api).clear_restart_after_restore("r-done")
    name, body = api.patched[-1]
    assert name == "r-done"
    assert body["metadata"]["annotations"][K8sClient.RESTART_AFTER_RESTORE] is None


def _source(*parts):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, *parts), encoding="utf-8") as f:
        return f.read()


def test_api_lets_kubevirt_stop_the_vm_durably_instead_of_refusing():
    """Панель отдавала 400 «остановите ВМ» — при том что кнопка отката всё
    равно перезагружает машину, а гасить её панель умеет и делает это при
    восстановлении из бэкапа."""
    src = _source("app", "api", "snapshots.py")
    assert "должна быть остановлена перед восстановлением" not in src
    assert "client.stop_vm(vm_name)" not in src
    assert '"targetReadinessPolicy": "StopTarget"' in _source("app", "core", "k8s_client.py")
    assert "wait_for_vm_stopped" not in src
    # Неудачный durable restore обрабатывает worker по условию Failure; API не
    # должен запускать target посреди неоднозначного create.
    core = _source("app", "core", "k8s_client.py")
    assert 'condition.get("type") == "Failure"' in core


def test_frontend_uses_ready_to_use_and_refreshes_pending_snapshots():
    """Succeeded без readyToUse — не точка отката. Интерфейс
    раньше писал «Готов» и включал кнопку, хотя API верно отказывал.
    Кроме того, Pending обновлялся только после перезагрузки страницы."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "components", "VMDetail.jsx"), encoding="utf-8") as f:
        src = f.read()

    assert "snapshot.ready_to_use === true" in src
    assert "disabled={restoring !== null || operationLocked || !snapshotReady(s)}" in src
    assert "Недоступен" in src
    assert "const intervalMs = hasPendingSnapshot ? 3000 : 30000" in src
    assert "setInterval(() => fetchSnapshots({ silent: true }), intervalMs)" in src
    assert "cache: 'no-store'" in src
    assert "'indeterminate'" in src
    assert "snapshot-restore:" in src
    assert "actionLoading !== null || backupLocked" in src


def test_worker_runs_the_restart_daemon():
    """Без регистрации потока пометка на объекте отката никого не разбудит."""
    src = _source("app", "worker.py")
    assert "def snapshot_restart_daemon" in src
    assert "restart_vms_after_finished_snapshot_restores(k8s, logger)" in src
    assert "target=snapshot_restart_daemon" in src


def test_worker_runs_the_backup_restart_daemon():
    """Terminal DataVolume не включит ВМ, если тик не
    зарегистрирован в main как фоновый поток."""
    src = _source("app", "worker.py")
    assert "def backup_restart_daemon" in src
    assert "restart_vms_after_finished_backups(k8s, logger)" in src
    assert "target=backup_restart_daemon" in src


class FakeStorageApi:
    def __init__(self, provisioners, parameters=None):
        self.provisioners = provisioners
        self.parameters = parameters or {}

    def read_storage_class(self, name):
        if name not in self.provisioners:
            raise ApiException(status=404)
        return type("SC", (), {
            "provisioner": self.provisioners[name],
            "parameters": self.parameters.get(name, {}),
        })()


class FakeCoreApi:
    def __init__(self, pvc_classes, pv_names=None):
        self.pvc_classes = pvc_classes
        self.pv_names = pv_names or {}

    def read_namespaced_persistent_volume_claim(self, name, ns):
        if name not in self.pvc_classes:
            raise ApiException(status=404)
        spec = type("Spec", (), {
            "storage_class_name": self.pvc_classes[name],
            "volume_name": self.pv_names.get(name),
        })()
        return type("PVC", (), {"spec": spec})()


class SnapshotApi(FakeCustomApi):
    """custom-objects API со снимками ВМ и классами снимков томов."""

    def __init__(self, snapshots=(), drivers=(), vm_volumes=(), lvm_volumes=()):
        super().__init__()
        self.snapshots = list(snapshots)
        self.drivers = list(drivers)
        self.vm_volumes = list(vm_volumes)
        self.lvm_volumes = list(lvm_volumes)

    def list_namespaced_custom_object(self, group, version, ns, plural):
        if plural == "virtualmachinesnapshots":
            return {"items": self.snapshots}
        return {"items": []}

    def list_cluster_custom_object(self, group, version, plural):
        if plural == "lvmvolumes":
            return {"items": self.lvm_volumes}
        return {"items": [{"driver": d} for d in self.drivers]}

    def get_namespaced_custom_object(self, group, version, ns, plural, name):
        if plural == "virtualmachines":
            return {"spec": {"template": {"spec": {"volumes": [
                {"dataVolume": {"name": v}} for v in self.vm_volumes
            ]}}}}
        raise ApiException(status=404)


def _snapshot(name, vm="vm1", included=(), excluded=()):
    return {
        "metadata": {"name": name, "creationTimestamp": "2026-08-15T12:03:05Z"},
        "spec": {"source": {"name": vm}},
        "status": {
            "phase": "Succeeded",
            "readyToUse": True,
            "snapshotVolumes": {
                "includedVolumes": list(included),
                "excludedVolumes": list(excluded),
            },
        },
    }


def test_snapshot_without_the_disk_is_not_reported_as_ready():
    """Самая дорогая из найденных ошибок: KubeVirt ставит Succeeded и
    readyToUse даже когда снял ОДНО ОПИСАНИЕ ВМ, а том положил в
    excludedVolumes — так бывает, когда под класс хранения диска нет
    подходящего VolumeSnapshotClass. Панель показывала «Готов», откат
    проходил без ошибок и возвращал конфиг ВМ, но не диск: приложение,
    установленное после снимка, оставалось на месте. Пользователь при этом
    уверен, что точка отката у него есть."""
    api = SnapshotApi(snapshots=[
        _snapshot("snap-empty", excluded=["vm1-disk"]),
        _snapshot("snap-real", included=["vm1-disk"]),
    ])
    c = _client(api)
    snaps = {s["name"]: s for s in c.list_vm_snapshots("vm1")}

    assert snaps["snap-empty"]["has_disk"] is False
    assert snaps["snap-empty"]["excluded_volumes"] == ["vm1-disk"]
    # Фаза от KubeVirt приходит успешной — на неё и нельзя опираться.
    assert snaps["snap-empty"]["phase"] == "Succeeded"
    assert snaps["snap-real"]["has_disk"] is True


def test_support_check_matches_the_driver_to_the_vm_disk():
    """Наличия хоть какого-нибудь класса снимков мало, а проверялось именно
    оно. После установки LVM в кластере появляется класс с driver
    local.csi.openebs.io — проверка «есть хоть один» проходит, при том что
    диск ВМ остался на local-path с провизионером rancher.io/local-path."""
    api = SnapshotApi(drivers=["local.csi.openebs.io"], vm_volumes=["vm1-disk"])
    c = _client(api)
    c.core_api = FakeCoreApi({"vm1-disk": "local-path"})
    c.storage_api = FakeStorageApi({"local-path": "rancher.io/local-path"})

    support = c.snapshot_support("vm1")
    assert support["supported"] is False
    assert support["unsupported"] == [
        {
            "storage_class": "local-path",
            "provisioner": "rancher.io/local-path",
            "reason": "snapshot_driver_missing",
        }
    ]


def test_support_check_passes_when_the_driver_matches():
    api = SnapshotApi(drivers=["local.csi.openebs.io"], vm_volumes=["vm1-disk"])
    c = _client(api)
    c.core_api = FakeCoreApi({"vm1-disk": "openebs-lvm"})
    c.storage_api = FakeStorageApi(
        {"openebs-lvm": "local.csi.openebs.io"},
        {"openebs-lvm": {"thinProvision": "yes"}},
    )

    assert _client(api) is not None
    support = c.snapshot_support("vm1")
    assert support["supported"] is True
    assert support["unsupported"] == []


def test_support_check_rejects_thick_openebs_lvm():
    api = SnapshotApi(drivers=["local.csi.openebs.io"], vm_volumes=["vm1-disk"])
    c = _client(api)
    c.core_api = FakeCoreApi({"vm1-disk": "openebs-lvm"})
    c.storage_api = FakeStorageApi(
        {"openebs-lvm": "local.csi.openebs.io"},
        {"openebs-lvm": {"thinProvision": "no"}},
    )

    support = c.snapshot_support("vm1")
    assert support["supported"] is False
    assert support["unsupported"][0]["reason"] == "thin_required"


def test_real_thick_pv_is_not_misreported_by_a_recreated_thin_storageclass():
    """Пересоздание SC под тем же именем не превращает старый PV в thin."""
    api = SnapshotApi(
        drivers=["local.csi.openebs.io"],
        vm_volumes=["vm1-disk"],
        lvm_volumes=[{
            "metadata": {"name": "pvc-old"},
            "spec": {"thinProvision": "no"},
        }],
    )
    c = _client(api)
    c.core_api = FakeCoreApi(
        {"vm1-disk": "openebs-lvm"}, {"vm1-disk": "pvc-old"},
    )
    c.storage_api = FakeStorageApi(
        {"openebs-lvm": "local.csi.openebs.io"},
        {"openebs-lvm": {"thinProvision": "yes"}},
    )

    support = c.snapshot_support("vm1")
    assert support["supported"] is False
    assert support["unsupported"][0]["reason"] == "thin_required"


def test_disk_classes_come_from_real_pvcs_not_the_template():
    """dataVolumeTemplates говорит, что просили при создании; снимать
    придётся то, что получилось. Диск, добавленный горячей заменой позже, в
    шаблоне не значится вовсе."""
    api = SnapshotApi(vm_volumes=["vm1-disk", "vm1-extra"])
    c = _client(api)
    c.core_api = FakeCoreApi({"vm1-disk": "openebs-lvm", "vm1-extra": "local-path"})
    c.storage_api = FakeStorageApi({})
    assert c.vm_disk_storage_classes("vm1") == ["openebs-lvm", "local-path"]


def test_rollback_from_an_empty_snapshot_is_refused():
    """Откат таким снимком отрабатывает без ошибок и не меняет ничего —
    выдавать это за откат нельзя."""
    src = _source("app", "api", "snapshots.py")
    restore = src[src.index("def restore_snapshot"):]
    assert 'if not snap.get("has_disk", True):' in restore
    assert "Откат невозможен" in restore
    # Проверка должна стоять ДО создания durable restore: иначе контроллер
    # зря остановит target через StopTarget.
    assert restore.index("has_disk") < restore.index("client.restore_vm_snapshot")


def test_creation_names_the_actual_storage_class_in_the_error():
    """«В кластере нет ни одного VolumeSnapshotClass» — не тот случай и не та
    подсказка, когда класс есть, а диск лежит на чужом провизионере."""
    src = _source("app", "api", "snapshots.py")
    assert "client.snapshot_support(vm_name)" in src
    assert "провизионер" in src
    assert "пересоздайте ВМ" in src, "диск существующей машины на другой класс не переедет"


def _content(name, ready_flags):
    return {"status": {"volumeSnapshotStatus": [
        {"volumeSnapshotName": f"{name}-vol{i}", "readyToUse": r}
        for i, r in enumerate(ready_flags)
    ]}}


class ProgressApi(SnapshotApi):
    """Снимки вместе с их VirtualMachineSnapshotContent."""

    def __init__(self, snapshots=(), contents=None):
        super().__init__(snapshots=snapshots)
        self.contents = contents or {}

    def get_namespaced_custom_object(self, group, version, ns, plural, name):
        if plural == "virtualmachinesnapshotcontents":
            if name not in self.contents:
                raise ApiException(status=404)
            return self.contents[name]
        return super().get_namespaced_custom_object(group, version, ns, plural, name)


def _in_progress(name, included, content_name=None):
    snap = _snapshot(name, included=included)
    snap["status"]["phase"] = "InProgress"
    snap["status"]["readyToUse"] = False
    if content_name:
        snap["status"]["virtualMachineSnapshotContentName"] = content_name
    return snap


def test_progress_counts_volumes_that_are_actually_ready():
    """Тонкого процента у снимка ВМ нет: KubeVirt его не считает, а снимок
    тома делается копированием при записи — промежуточным значениям взяться
    неоткуда. Настоящая мера одна: сколько томов уже readyToUse."""
    api = ProgressApi(
        snapshots=[_in_progress("snap-multi", ["a", "b", "c"], content_name="c-multi")],
        contents={"c-multi": _content("snap-multi", [True, True, False])},
    )
    snap = _client(api).list_vm_snapshots("vm1")[0]
    assert snap["volumes_ready"] == 2
    assert snap["volumes_total"] == 3
    assert snap["progress_percent"] == 67


def test_progress_is_zero_before_the_content_object_appears():
    """KubeVirt только принял объект — считать ещё нечего, но строка уже
    должна показывать, что дело пошло."""
    api = ProgressApi(snapshots=[_in_progress("snap-new", ["a"])])
    snap = _client(api).list_vm_snapshots("vm1")[0]
    assert snap["progress_percent"] == 0
    assert snap["volumes_ready"] == 0


def test_ready_snapshot_reports_full_progress_without_extra_calls():
    """У готового снимка контент запрашивать незачем — список снимков
    опрашивается циклически, и лишний запрос на каждый снимок в каждом тике
    ощутимо дороже одной проверки флага."""
    class NoContent(ProgressApi):
        def get_namespaced_custom_object(self, group, version, ns, plural, name):
            # Только за контентом: состав томов ВМ читается один раз на весь
            # список и к прогрессу отношения не имеет.
            if plural == "virtualmachinesnapshotcontents":
                raise AssertionError("готовый снимок не должен ходить за контентом")
            return super().get_namespaced_custom_object(group, version, ns, plural, name)

    api = NoContent(snapshots=[_snapshot("snap-done", included=["a"])])
    snap = _client(api).list_vm_snapshots("vm1")[0]
    assert snap["progress_percent"] == 100
    assert snap["volumes_ready"] == snap["volumes_total"] == 1


def test_backup_progress_bar_shows_before_cdi_reports_a_number():
    """Условие progress !== 'N/A' прятало полосу целиком в самом начале —
    ровно тогда, когда смотришь, пошло ли дело: копия висела строкой без
    единого признака движения."""
    # Три уровня вверх: tests -> backend -> корень репозитория.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "components", "BackupList.jsx"), encoding="utf-8") as f:
        src = f.read()
    assert "b.progress !== 'N/A' &&" not in src
    assert "{isBusy(b) && (" in src
    # Ноль означал бы «посчитано и ничего не сделано» — это не то же самое.
    assert "'идёт…'" in src
    assert "'indeterminate'" in src
    assert "cache: 'no-store'" in src


def test_backup_surfaces_why_it_is_stuck():
    """Сама фаза не объясняет ничего: «Unknown» одинаково выглядит и у копии,
    созданной секунду назад, и у той, которой некуда лечь. Причину CDI пишет
    в conditions — «no persistent volumes available for this claim» и
    подобное. Без неё пользователю остаётся гадать, ждать или чинить."""
    stuck = {"conditions": [
        {"type": "Bound", "status": "False",
         "message": "no persistent volumes available for this claim"},
        {"type": "Ready", "status": "False", "reason": "Pending"},
    ]}
    assert K8sClient._datavolume_detail(stuck) == \
        "no persistent volumes available for this claim"

    # Условие в порядке ничего не объясняет — показывать его незачем.
    healthy = {"conditions": [{"type": "Bound", "status": "True", "message": "claim bound"}]}
    assert K8sClient._datavolume_detail(healthy) is None
    assert K8sClient._datavolume_detail({}) is None


def test_panel_is_told_about_broken_snapshots_before_creating_one():
    """Пользователь видел ноль процентов, которому нечем двигаться — тома в
    снимке нет, — а через минуту вместо результата получал «Без диска».
    Причину надо называть заранее, а не показывать полосу, которая заведомо
    не дойдёт до конца."""
    src = _source("app", "api", "snapshots.py")
    assert '@router.get("/{vm_name}/support")' in src
    # Один и тот же текст у отказа и у предупреждения: две формулировки
    # неизбежно разойдутся.
    assert src.count("_unsupported_reason(support)") == 3


def test_support_check_failure_does_not_block_the_panel():
    """Диагностика не должна мешать работать: не смогли проверить — не
    запрещаем, отказ при создании всё равно сработает."""
    src = _source("app", "api", "snapshots.py")
    block = src[src.index("def snapshot_support("):src.index('@router.get("/{vm_name}", response_model')]
    assert '{"supported": True, "reason": None}' in block


def test_warning_style_exists_for_things_that_are_not_broken():
    """Набор alert обрывался на info, и такие места красили в danger — то есть
    выдавали за поломку то, что ею не является."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "frontend", "src", "index.css"), encoding="utf-8") as f:
        css = f.read()
    assert ".alert-warning {" in css
    assert '[data-theme="dark"] .alert-warning' in css, "в тёмной теме текст утонет в фоне"


class VmVolumesApi(ProgressApi):
    """Снимки + состав томов ВМ (нужен, чтобы отличать cloud-init от диска)."""

    def __init__(self, snapshots=(), volumes=()):
        super().__init__(snapshots=snapshots)
        self.volumes = list(volumes)

    def get_namespaced_custom_object(self, group, version, ns, plural, name):
        if plural == "virtualmachines":
            return {"spec": {"template": {"spec": {"volumes": self.volumes}}}}
        return super().get_namespaced_custom_object(group, version, ns, plural, name)


VM_VOLUMES = [
    {"name": "datavolumedisk", "dataVolume": {"name": "gbgb-disk"}},
    {"name": "cloudinitdisk", "cloudInitNoCloud": {"userData": "#cloud-config"}},
]


def test_cloud_init_being_excluded_does_not_condemn_the_snapshot():
    """Проверка «исключён хоть один том — значит снимок пустой» ломала
    исправные снимки. У каждой ВМ этой панели есть cloudinitdisk — том
    cloudInitNoCloud, а не PVC, — и KubeVirt исключает его ВСЕГДА, снимать
    там нечего. Полностью рабочий снимок диска на openebs-lvm из-за этого
    помечался «Без диска», и откатить им было нельзя."""
    api = VmVolumesApi(
        snapshots=[_snapshot("snap-ok", included=["datavolumedisk"], excluded=["cloudinitdisk"])],
        volumes=VM_VOLUMES,
    )
    snap = _client(api).list_vm_snapshots("vm1")[0]
    assert snap["has_disk"] is True
    assert snap["missing_volumes"] == []


def test_a_real_disk_left_out_is_still_reported():
    """А вот исключённый том, за которым стоит настоящий диск, — как раз то,
    ради чего проверка и заводилась."""
    api = VmVolumesApi(
        snapshots=[_snapshot("snap-bad", included=[], excluded=["datavolumedisk", "cloudinitdisk"])],
        volumes=VM_VOLUMES,
    )
    snap = _client(api).list_vm_snapshots("vm1")[0]
    assert snap["has_disk"] is False
    assert snap["missing_volumes"] == ["datavolumedisk"]


def test_unknown_vm_layout_falls_back_to_suspecting_everything():
    """Машину могли уже удалить. Выдумывать в этом случае нельзя — считаем
    любой исключённый том подозрительным, как было до появления проверки."""
    class NoVm(VmVolumesApi):
        def get_namespaced_custom_object(self, group, version, ns, plural, name):
            if plural == "virtualmachines":
                raise ApiException(status=404)
            return super().get_namespaced_custom_object(group, version, ns, plural, name)

    api = NoVm(snapshots=[_snapshot("s", included=["d"], excluded=["cloudinitdisk"])])
    snap = _client(api).list_vm_snapshots("vm1")[0]
    assert snap["has_disk"] is False


def test_backup_clone_carries_the_modes_of_the_source_disk():
    """Без явных accessModes/volumeMode CDI идёт за ними в StorageProfile, а у
    openebs-lvm он пустой — бэкап вставал намертво:

        ErrClaimNotValid: no accessMode specified in StorageProfile openebs-lvm

    Снаружи это «копия создалась и вечно висит в неизвестном состоянии».
    Режимы обязаны совпадать с исходником ещё и потому, что клон между Block
    и Filesystem CDI не делает."""
    from app.core.k8s_client import _clone_target_modes

    spec = type("Spec", (), {"access_modes": ["ReadWriteOnce"], "volume_mode": "Block"})()
    pvc = type("PVC", (), {"spec": spec})()
    assert _clone_target_modes(pvc) == {"accessModes": ["ReadWriteOnce"], "volumeMode": "Block"}

    # Исходник ничего не сообщил — пусть решает CDI, это лучше, чем наугад.
    bare = type("PVC", (), {"spec": type("Spec", (), {"access_modes": None, "volume_mode": None})()})()
    assert _clone_target_modes(bare) == {}


def test_both_clone_paths_set_the_modes():
    """И backup, и staged-restore обязаны повторять режим исходного PVC."""
    src = _source("app", "core", "k8s_client.py")
    assert src.count("**_clone_target_modes(") == 2


def test_installer_fills_the_storage_profile():
    """CDI заполняет StorageProfile сам только для классов, которые знает в
    лицо; для openebs-lvm он остаётся пустым."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "scripts", "install-openebs-lvm.sh"), encoding="utf-8") as f:
        sh = f.read()
    assert "kubectl patch storageprofile openebs-lvm" in sh
    assert '"volumeMode": "Filesystem"' in sh
    assert "|| log" in sh, "падение патча не должно ронять установку под set -e"
