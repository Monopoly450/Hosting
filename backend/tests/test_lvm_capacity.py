"""LVM-пул (и локальный диск, когда LVM не активен) не должны позволять
занять больше места, чем у них физически есть — диском ВМ, бэкапом,
сетевым диском или базой данных: все они делят один и тот же
STORAGE_CLASS и, следовательно, один и тот же бэкенд хранения."""
import inspect

import pytest
from fastapi import HTTPException

from app.core import capacity as cap
from tests.test_host_capacity_guard import FakeDb, FakeVM


class FakeVol:
    def __init__(self, size_gb): self.size_gb = size_gb


class FakeDatabase:
    pass


# ------------------------------ is_lvm_storage_class -------------------------

@pytest.mark.parametrize("name", ["openebs-lvmpv", "vg-aegis-sc", "LVM-thin", "my-vg-pool"])
def test_lvm_names_are_recognised(name):
    assert cap.is_lvm_storage_class(name) is True


@pytest.mark.parametrize("name", ["local-path", "nfs-client", "", None])
def test_non_lvm_names_are_not_mistaken_for_lvm(name):
    assert cap.is_lvm_storage_class(name) is False


# ------------------------------ storage_backend_totals ------------------------

def test_thin_pool_free_space_is_not_lost_from_capacity():
    """vgs считает thin-pool выделенным целиком, но его незаписанная часть
    остаётся доступной. Иначе первый PVC визуально съедал почти всю VG."""
    result = cap._parse_lvm_capacity(
        "100.00 20.00\n",
        "80.00|25.00|thin-pool\n1.00||linear\n",
    )
    assert result == {"active": True, "total_gb": 100.0, "free_gb": 80.0}


def test_thick_pool_capacity_remains_vg_free():
    assert cap._parse_lvm_capacity("100,00 42,50\n") == {
        "active": True, "total_gb": 100.0, "free_gb": 42.5,
    }


def test_lvm_free_space_is_clamped_to_sparse_image_backing_fs(monkeypatch):
    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    results = iter([
        Result("100.00 20.00\n"),
        Result("80.00|25.00|thin-pool\n"),
    ])
    monkeypatch.setattr("subprocess.run", lambda *a, **k: next(results))
    monkeypatch.setattr(cap, "_lvm_backing_free_gb", lambda: 12.0)

    assert cap.read_lvm_pool_gb() == {
        "active": True, "total_gb": 100.0, "free_gb": 12.0,
    }

def test_local_path_routes_to_the_host_disk(monkeypatch):
    """Настройка по умолчанию — то, что уже наблюдалось на живом сервере:
    LVM-пул существует, но пуст, потому что STORAGE_CLASS на него не указывает."""
    monkeypatch.setattr(cap, "host_totals", lambda: {
        "cpu": 1, "ram_gb": 1.0, "ram_used_gb": 0.0, "disk_gb": 200.0, "disk_free_gb": 150.0})

    class Settings:
        STORAGE_CLASS = "local-path"
    monkeypatch.setattr("app.core.config.settings", Settings())

    result = cap.storage_backend_totals()
    assert result == {"backend": "local", "total_gb": 200.0, "free_gb": 150.0}


def test_lvm_backed_class_routes_to_the_pool(monkeypatch):
    monkeypatch.setattr(cap, "read_lvm_pool_gb", lambda: {"active": True, "total_gb": 50.0, "free_gb": 50.0})

    class Settings:
        STORAGE_CLASS = "openebs-lvmpv"
    monkeypatch.setattr("app.core.config.settings", Settings())

    result = cap.storage_backend_totals()
    assert result == {"backend": "lvm", "total_gb": 50.0, "free_gb": 50.0}


def test_lvm_configured_but_unreachable_fails_closed(monkeypatch):
    """Корневой диск не является запасным backend для openebs-lvm: если VG
    недоступен, новые PVC должны остановиться, а не пройти чужую ёмкость."""
    monkeypatch.setattr(cap, "read_lvm_pool_gb", lambda: {"active": False, "total_gb": 0.0, "free_gb": 0.0})
    monkeypatch.setattr(cap, "host_totals", lambda: {
        "cpu": 1, "ram_gb": 1.0, "ram_used_gb": 0.0, "disk_gb": 200.0, "disk_free_gb": 150.0})

    class Settings:
        STORAGE_CLASS = "openebs-lvmpv"
    monkeypatch.setattr("app.core.config.settings", Settings())

    result = cap.storage_backend_totals()
    assert result == {"backend": "lvm", "total_gb": 0.0, "free_gb": 0.0}


# ------------------------------ known_storage_reservations_gb -----------------

def test_reservations_sum_vm_disks_volumes_and_databases():
    db = FakeDb(
        vms=[FakeVM(1, 1, 20), FakeVM(1, 1, 30)],
        volumes=[FakeVol(10), FakeVol(5)],
        databases=[FakeDatabase(), FakeDatabase()],
    )
    # 20 + 30 (диски ВМ) + 10 + 5 (сетевые диски) + 2×5 (базы данных, DB_PVC_SIZE_GB)
    assert cap.known_storage_reservations_gb(db) == 20 + 30 + 10 + 5 + 2 * 5


def test_reservations_without_k8s_client_skip_backups():
    """Размеры бэкапов не хранятся в БД — без k8s-клиента их посчитать
    неоткуда, и функция не должна пытаться."""
    db = FakeDb(vms=[FakeVM(1, 1, 20)])
    assert cap.known_storage_reservations_gb(db, k8s=None) == 20


def test_reservations_with_k8s_client_include_backups(monkeypatch):
    monkeypatch.setattr(cap, "backups_total_gb", lambda k8s, strict=False: 15.0)
    db = FakeDb(vms=[FakeVM(1, 1, 20)])
    assert cap.known_storage_reservations_gb(db, k8s=object()) == 20 + 15.0


# ------------------------------ backups_total_gb ------------------------------

class FakeCustomApi:
    def __init__(self, items): self._items = items
    def list_cluster_custom_object(self, group, version, plural):
        return {"items": self._items}


class FakeK8s:
    def __init__(self, items): self.custom_api = FakeCustomApi(items)


def _dv(size, labelled=True):
    return {
        "metadata": {"labels": {"hosting.antigravity.io/backup-source": "vm1"} if labelled else {}},
        "spec": {"storage": {"resources": {"requests": {"storage": size}}}},
    }


def test_backups_total_gb_sums_only_labelled_datavolumes():
    """Не всякий DataVolume — бэкап: обычный диск ВМ тоже DataVolume, но без
    метки backup-source, и его нельзя засчитывать дважды."""
    k8s = FakeK8s([_dv("20Gi"), _dv("30Gi"), _dv("999Gi", labelled=False)])
    assert cap.backups_total_gb(k8s) == 50.0


def test_active_staged_restore_counts_as_a_temporary_full_clone():
    restore = _dv("20Gi", labelled=False)
    restore["metadata"]["labels"] = {
        "hosting.antigravity.io/restore-operation": "restore-op",
    }
    assert cap.backups_total_gb(FakeK8s([restore])) == 20.0


def test_backups_total_gb_understands_mebibytes():
    k8s = FakeK8s([_dv("512Mi")])
    assert cap.backups_total_gb(k8s) == 0.5


def test_backups_total_gb_is_zero_when_kubernetes_is_unreachable():
    class BrokenApi:
        def list_cluster_custom_object(self, *a, **k):
            raise Exception("connection refused")
    k8s = type("K", (), {"custom_api": BrokenApi()})()
    assert cap.backups_total_gb(k8s) == 0.0


def test_backup_inventory_failure_is_strict_for_allocation_checks():
    class BrokenApi:
        def list_cluster_custom_object(self, *a, **k):
            raise RuntimeError("connection refused")
    k8s = type("K", (), {"custom_api": BrokenApi()})()
    with pytest.raises(RuntimeError):
        cap.backups_total_gb(k8s, strict=True)


# ------------------------------ ensure_storage_capacity -----------------------

def test_request_within_the_pool_is_allowed(monkeypatch):
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "lvm", "total_gb": 50.0, "free_gb": 50.0})
    cap.ensure_storage_capacity(FakeDb(), extra_gb=10)


def test_existing_backups_are_subtracted_by_live_allocation_check(monkeypatch):
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "lvm", "total_gb": 50.0, "free_gb": 50.0})
    monkeypatch.setattr(cap, "backups_total_gb", lambda k8s, strict=False: 30.0)
    with pytest.raises(HTTPException):
        cap.ensure_storage_capacity(FakeDb(), extra_gb=25, k8s=object())


def test_request_beyond_the_pool_is_refused_with_the_real_backend_named(monkeypatch):
    """Симптом с живого сервера: LVM-пул на 50 ГБ, диск на 100 ГБ проходил
    проверку, потому что она смотрела на весь диск хоста (148 ГБ свободных),
    а не на реальный, куда меньший потолок самого пула."""
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "lvm", "total_gb": 50.0, "free_gb": 50.0})
    with pytest.raises(HTTPException) as exc:
        cap.ensure_storage_capacity(FakeDb(), extra_gb=100)
    assert exc.value.status_code == 400
    assert "LVM-пуле" in exc.value.detail


def test_local_backend_is_named_correctly_in_the_refusal(monkeypatch):
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "local", "total_gb": 200.0, "free_gb": 5.0})
    with pytest.raises(HTTPException) as exc:
        cap.ensure_storage_capacity(FakeDb(), extra_gb=50)
    assert "локальном диске хоста" in exc.value.detail


def test_existing_reservations_are_subtracted_before_checking(monkeypatch):
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "lvm", "total_gb": 50.0, "free_gb": 50.0})
    db = FakeDb(vms=[FakeVM(1, 1, 45)])
    with pytest.raises(HTTPException):
        cap.ensure_storage_capacity(db, extra_gb=10)  # 45 занято + 10 новых > 50


def test_zero_extra_gb_always_technically_fits():
    """0 запрошенных ГБ математически влезает в любое неотрицательное
    свободное место — включая ровно ноль. Это не тот вопрос, который нужен
    для снимков (см. ensure_any_storage_headroom), а честная арифметика
    ensure_storage_capacity."""
    cap.ensure_storage_capacity(FakeDb(), extra_gb=0)


# ------------------------- ensure_any_storage_headroom (снимки) --------------

def test_headroom_check_refuses_a_fully_exhausted_pool(monkeypatch):
    """Снимки: конкретного числа ГБ нет (дифференциальный объект), но пул,
    в котором вообще не осталось места, — уже сам по себе достаточная причина
    отказать, а не создавать снимок, расти которому будет некуда."""
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "lvm", "total_gb": 50.0, "free_gb": 0.0})
    db = FakeDb(vms=[FakeVM(1, 1, 50)])
    with pytest.raises(HTTPException) as exc:
        cap.ensure_any_storage_headroom(db)
    assert "не осталось свободного места" in exc.value.detail


def test_headroom_check_passes_when_room_remains(monkeypatch):
    monkeypatch.setattr(cap, "storage_backend_totals",
                        lambda: {"backend": "lvm", "total_gb": 50.0, "free_gb": 10.0})
    db = FakeDb(vms=[FakeVM(1, 1, 40)])
    cap.ensure_any_storage_headroom(db)


# ------------------------- проверка реально подключена -----------------------

@pytest.mark.parametrize("module,func,guard", [
    ("app.api.databases", "create_database", "ensure_storage_capacity"),
    ("app.api.volumes", "create_volume", "ensure_storage_capacity"),
    ("app.api.vms", "create_backup", "ensure_storage_capacity"),
    ("app.api.vms", "restore_vm_backup", "ensure_storage_capacity"),
    # У снимка нет известного заранее размера (дифференциальный объект) —
    # см. ensure_any_storage_headroom.
    ("app.api.snapshots", "create_snapshot", "ensure_any_storage_headroom"),
])
def test_every_pvc_creating_endpoint_checks_storage_capacity(module, func, guard):
    """Диск ВМ, бэкап, сетевой диск и база данных — все создают PVC на одном
    и том же STORAGE_CLASS. Раньше только диск ВМ (частично — без учёта
    LVM-пула) и сетевой диск (сломанной, без nsenter, проверкой) хоть
    как-то смотрели на место; бэкап и база данных — никак."""
    import importlib

    mod = importlib.import_module(module)
    fn = getattr(mod, func, None)
    assert fn is not None, f"{module}.{func} не найден — тест устарел"
    src = inspect.getsource(fn)
    assert guard in src, f"{module}.{func} не проверяет вместимость хранилища"
    assert "lock_host_capacity" in src, f"{module}.{func} проверяет без блокировки"
    assert "k8s=" in src, f"{module}.{func} не учитывает существующие backup DataVolume"


def test_network_volume_no_longer_calls_vgs_directly():
    """Старая проверка звала vgs без nsenter — внутри контейнера это либо
    ничего не находило, либо падало, и code «доступно: None» проверку тихо
    пропускал. Теперь вся работа с vgs — в одном месте (capacity.py)."""
    from app.api import volumes

    src = inspect.getsource(volumes.create_volume)
    assert '"vgs"' not in src


def test_scheduled_vm_backup_uses_the_shared_storage_guard():
    """Фоновый планировщик не должен обходить проверку, которую проходит
    та же операция из панели."""
    from app.services import scheduled_backups

    src = inspect.getsource(scheduled_backups._execute_one)
    assert "lock_host_capacity" in src
    assert "ensure_storage_capacity" in src
    assert "k8s=k8s" in src


def test_dashboard_reuses_the_same_vgs_reader_as_the_capacity_check():
    """Раньше host.py и volumes.py каждый по-своему звали vgs. Дашборд и
    проверка вместимости должны сходиться в одном источнике данных, иначе
    они неизбежно разойдутся в показаниях."""
    from app.api import host

    src = inspect.getsource(host.get_host_metrics)
    assert "read_lvm_pool_gb" in src
