"""Ресурсы хоста должны проверяться на ВСЕХ путях создания ВМ."""
import inspect

import pytest
from fastapi import HTTPException

from app.core.capacity import ensure_host_capacity


class FakeVM:
    def __init__(self, cpu, ram, disk, status="Running"):
        self.cpu_cores, self.memory_gb, self.disk_gb, self.status = cpu, ram, disk, status


class FakeQuery:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows
    def count(self): return len(self._rows)


class FakeDb:
    """Отдаёт разные строки по разным моделям — как настоящая сессия
    SQLAlchemy, а не одну и ту же выдумку на все запросы. Нужно, поскольку
    ensure_storage_capacity опрашивает VMTask, UserVolume и UserDatabase
    раздельно (диски ВМ, сетевые диски и базы данных конкурируют за одно и
    то же место на активном бэкенде хранения)."""
    def __init__(self, vms=(), volumes=(), databases=()):
        self._vms, self._volumes, self._databases = list(vms), list(volumes), list(databases)

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "UserVolume":
            return FakeQuery(self._volumes)
        if name == "UserDatabase":
            return FakeQuery(self._databases)
        return FakeQuery(self._vms)


@pytest.fixture
def small_host(monkeypatch):
    """Хост пользователя: 10 ядер, 15 ГБ ОЗУ, 200 ГБ диска."""
    monkeypatch.setattr("app.core.capacity.host_totals", lambda: {
        "cpu": 10, "ram_gb": 15.0, "ram_used_gb": 1.0,
        "disk_gb": 200.0, "disk_free_gb": 190.0,
    })


def test_request_that_fits_is_allowed(small_host):
    ensure_host_capacity(FakeDb([]), cpu_cores=2, memory_gb=2, disk_gb=20)


def test_cpu_beyond_the_host_is_refused(small_host):
    """Именно так и набралось 22 зарезервированных ядра на 10-ядерном хосте."""
    db = FakeDb([FakeVM(8, 2, 20)])
    with pytest.raises(HTTPException) as exc:
        ensure_host_capacity(db, cpu_cores=4, memory_gb=1, disk_gb=10)
    assert exc.value.status_code == 400
    assert "ядер" in exc.value.detail


def test_ram_beyond_the_host_is_refused(small_host):
    db = FakeDb([FakeVM(1, 12, 20, status="Stopped")])
    with pytest.raises(HTTPException) as exc:
        ensure_host_capacity(db, cpu_cores=1, memory_gb=8, disk_gb=10)
    assert "памяти" in exc.value.detail


def test_disk_beyond_the_host_is_refused(small_host):
    db = FakeDb([FakeVM(1, 1, 190)])
    with pytest.raises(HTTPException) as exc:
        ensure_host_capacity(db, cpu_cores=1, memory_gb=1, disk_gb=50)
    assert "диск" in exc.value.detail.lower()


def test_the_message_says_how_much_is_already_reserved(small_host):
    """Иначе «доступно 0» выглядит необъяснимо."""
    db = FakeDb([FakeVM(9, 1, 10)])
    with pytest.raises(HTTPException) as exc:
        ensure_host_capacity(db, cpu_cores=4, memory_gb=1, disk_gb=1)
    assert "зарезервировано" in exc.value.detail


# ------- проверка подключена ко всем трём путям создания ВМ -----------------

@pytest.mark.parametrize("module,func", [
    ("app.api.marketplace", "deploy"),
    ("app.api.deployments", "create_deployment"),
])
def test_every_creation_path_checks_host_capacity(module, func):
    """Маркетплейс и деплой создавали VMTask напрямую, проверяя только квоту
    пользователя. Хост при этом не спрашивали вообще — через них и получилось
    «Занято ВМ: 22 ядра» при десяти физических."""
    import importlib

    mod = importlib.import_module(module)
    fn = getattr(mod, func, None)
    assert fn is not None, f"{module}.{func} не найден — тест устарел"
    src = inspect.getsource(fn)
    assert "ensure_host_capacity" in src, f"{module}.{func} не проверяет ресурсы хоста"
    assert "lock_host_capacity" in src, f"{module}.{func} проверяет без блокировки"


def test_vm_creation_endpoint_still_checks_capacity():
    from app.api import vms

    src = inspect.getsource(vms.create_vm)
    assert "lock_host_capacity" in src
