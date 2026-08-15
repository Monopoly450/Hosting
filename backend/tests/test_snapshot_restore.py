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
