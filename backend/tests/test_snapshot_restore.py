"""Откат на снимок при включённой ВМ."""
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from kubernetes.client.rest import ApiException

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


def test_api_stops_the_vm_instead_of_refusing():
    """Панель отдавала 400 «остановите ВМ» — при том что кнопка отката всё
    равно перезагружает машину, а гасить её панель умеет и делает это при
    восстановлении из бэкапа."""
    src = _source("app", "api", "snapshots.py")
    assert "должна быть остановлена перед восстановлением" not in src
    assert "client.stop_vm(vm_name)" in src
    assert "wait_for_vm_stopped" in src
    # Неудачный откат не должен оставлять пользователя с ошибкой И погашенной ВМ.
    restore = src[src.index("def restore_snapshot"):]
    assert "client.start_vm(vm_name)" in restore


def test_worker_runs_the_restart_daemon():
    """Без регистрации потока пометка на объекте отката никого не разбудит."""
    src = _source("app", "worker.py")
    assert "def snapshot_restart_daemon" in src
    assert "target=snapshot_restart_daemon" in src


class FakeStorageApi:
    def __init__(self, provisioners):
        self.provisioners = provisioners

    def read_storage_class(self, name):
        if name not in self.provisioners:
            raise ApiException(status=404)
        return type("SC", (), {"provisioner": self.provisioners[name]})()


class FakeCoreApi:
    def __init__(self, pvc_classes):
        self.pvc_classes = pvc_classes

    def read_namespaced_persistent_volume_claim(self, name, ns):
        if name not in self.pvc_classes:
            raise ApiException(status=404)
        spec = type("Spec", (), {"storage_class_name": self.pvc_classes[name]})()
        return type("PVC", (), {"spec": spec})()


class SnapshotApi(FakeCustomApi):
    """custom-objects API со снимками ВМ и классами снимков томов."""

    def __init__(self, snapshots=(), drivers=(), vm_volumes=()):
        super().__init__()
        self.snapshots = list(snapshots)
        self.drivers = list(drivers)
        self.vm_volumes = list(vm_volumes)

    def list_namespaced_custom_object(self, group, version, ns, plural):
        if plural == "virtualmachinesnapshots":
            return {"items": self.snapshots}
        return {"items": []}

    def list_cluster_custom_object(self, group, version, plural):
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
        {"storage_class": "local-path", "provisioner": "rancher.io/local-path"}
    ]


def test_support_check_passes_when_the_driver_matches():
    api = SnapshotApi(drivers=["local.csi.openebs.io"], vm_volumes=["vm1-disk"])
    c = _client(api)
    c.core_api = FakeCoreApi({"vm1-disk": "openebs-lvm"})
    c.storage_api = FakeStorageApi({"openebs-lvm": "local.csi.openebs.io"})

    assert _client(api) is not None
    support = c.snapshot_support("vm1")
    assert support["supported"] is True
    assert support["unsupported"] == []


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
    # Проверка должна стоять ДО остановки ВМ: иначе машину гасят зря.
    assert restore.index("has_disk") < restore.index("client.stop_vm")


def test_creation_names_the_actual_storage_class_in_the_error():
    """«В кластере нет ни одного VolumeSnapshotClass» — не тот случай и не та
    подсказка, когда класс есть, а диск лежит на чужом провизионере."""
    src = _source("app", "api", "snapshots.py")
    assert "client.snapshot_support(vm_name)" in src
    assert "провизионер" in src
    assert "пересоздайте ВМ" in src, "диск существующей машины на другой класс не переедет"
