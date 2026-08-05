"""Проверка того, что запрошенные ресурсы действительно есть на хосте.

Отличается от квот (app.core.quotas): квота ограничивает конкретного
пользователя, а здесь речь о физической вместимости сервера, общей для всех.

Две проблемы, найденные на живом сервере при одновременном создании 10 ВМ:

1. Диск считался «свободным» по shutil.disk_usage, без учёта того, сколько
   места уже обещано существующим ВМ. Диски KubeVirt/CDI создаются тонкими и
   растут по мере записи, поэтому сразу после создания ВМ свободное место
   почти не уменьшается. Десять ВМ по 50 ГБ на сервере со 100 ГБ свободного
   места проходили проверку все до одной — а потом навсегда зависали в
   планировании, потому что выделить обещанное было уже неоткуда. CPU и ОЗУ
   резервирование учитывали, диск — нет.

2. Проверка «сколько осталось» и вставка новой ВМ — две отдельные операции.
   Без блокировки десять параллельных запросов читают одно и то же состояние
   и проходят проверку все одновременно. У обычного пользователя это ловилось
   квотой (она берёт блокировку строки пользователя), но для админа
   enforce_quota выходит сразу же, ничего не блокируя, — а именно админ и
   разворачивает пачку ВМ.
"""
import logging

from sqlalchemy import text

logger = logging.getLogger("app.core.capacity")

# Произвольный, но постоянный ключ advisory-блокировки Postgres: "Aegi".
# Блокировка транзакционная — снимается сама вместе с commit/rollback/close.
HOST_CAPACITY_LOCK_KEY = 0x41656769


def lock_host_capacity(db):
    """Сериализует проверку ресурсов хоста между параллельными запросами.

    Блокировка общая для всех пользователей (в отличие от квотной, которая
    берётся на строку пользователя): вместимость сервера — общий ресурс.
    Вызывать ДО подсчёта занятого и в той же транзакции, что и вставка ВМ.
    """
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                   {"k": HOST_CAPACITY_LOCK_KEY})
    except Exception as e:
        # SQLite в тестах advisory-блокировок не умеет — проверка ресурсов
        # не должна из-за этого падать.
        logger.warning(f"Не удалось взять блокировку вместимости хоста: {e}")
        db.rollback()


def reserved_disk_gb(db) -> float:
    """Сколько дискового пространства уже обещано существующим ВМ."""
    from app.models.models import VMTask
    return float(sum(vm.disk_gb or 0 for vm in db.query(VMTask).all()))


def host_totals() -> dict:
    """Физические ресурсы хоста: ядра, ОЗУ, диск (всего и свободно)."""
    import os
    import shutil

    totals = {"cpu": os.cpu_count() or 1, "ram_gb": 0.0,
              "disk_gb": 0.0, "disk_free_gb": 0.0, "ram_used_gb": 0.0}
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])
        total = mem.get("MemTotal", 0) * 1024
        free = mem.get("MemFree", 0) * 1024
        buffers = mem.get("Buffers", 0) * 1024
        cached = mem.get("Cached", 0) * 1024
        totals["ram_gb"] = round(total / (1024 ** 3), 2)
        totals["ram_used_gb"] = round((total - (free + buffers + cached)) / (1024 ** 3), 2)
    except Exception as e:
        logger.warning(f"Не удалось прочитать /proc/meminfo: {e}")
    try:
        total, _used, free = shutil.disk_usage("/")
        totals["disk_gb"] = round(total / (1024 ** 3), 2)
        totals["disk_free_gb"] = round(free / (1024 ** 3), 1)
    except Exception as e:
        logger.warning(f"Не удалось определить размер диска: {e}")
    return totals


def ensure_host_capacity(db, *, cpu_cores: int, memory_gb: int, disk_gb: int):
    """Проверяет, что ВМ с такими ресурсами физически влезет на хост.

    Отдельно от квот: квота — про лимит пользователя, здесь — про то, что
    железа столько есть. Раньше эта проверка была ТОЛЬКО на странице создания
    ВМ, а маркетплейс и деплой из репозитория создавали VMTask напрямую,
    вообще ничего не проверяя. Через них и набралось 22 зарезервированных
    ядра на 10-ядерном хосте и 22 ГБ ОЗУ на 15 ГБ — панель показывала
    «Доступно для новых ВМ: 0», а ВМ продолжали создаваться и намертво
    вставали в планировании, потому что выделить обещанное было неоткуда.

    Вызывать под lock_host_capacity и в одной транзакции с созданием ВМ.
    """
    from fastapi import HTTPException
    from app.models.models import VMTask

    host = host_totals()
    vms = db.query(VMTask).all()
    reserved_cpu = sum(vm.cpu_cores or 0 for vm in vms)
    reserved_stopped_ram = sum(vm.memory_gb or 0 for vm in vms if vm.status != "Running")
    reserved_disk = sum(vm.disk_gb or 0 for vm in vms)

    free_cpu = max(0, host["cpu"] - reserved_cpu)
    free_ram = max(0.0, round(host["ram_gb"] - host["ram_used_gb"] - reserved_stopped_ram, 2))
    free_disk = available_disk_gb(host["disk_gb"], host["disk_free_gb"], reserved_disk)

    if cpu_cores > free_cpu:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно свободных ядер CPU на хосте. Запрошено: {cpu_cores}, "
                   f"доступно: {free_cpu} (всего {host['cpu']}, "
                   f"уже зарезервировано другими ВМ: {reserved_cpu}).")
    if memory_gb > free_ram:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно свободной оперативной памяти на хосте. Запрошено: "
                   f"{memory_gb} ГБ, доступно: {free_ram} ГБ (всего {host['ram_gb']} ГБ).")
    if disk_gb > free_disk:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно свободного места на диске. Запрошено: {disk_gb} ГБ, "
                   f"доступно: {free_disk} ГБ (всего {host['disk_gb']} ГБ, "
                   f"уже зарезервировано другими ВМ: {reserved_disk} ГБ).")


def available_disk_gb(host_disk_total_gb: float, host_disk_free_gb: float,
                      reserved_gb: float) -> float:
    """Сколько диска можно обещать новой ВМ.

    Берём меньшее из двух оценок, потому что каждая ловит свой случай:

    * host_disk_free_gb — реально свободное место. Ловит ситуацию, когда диск
      занят не виртуалками (образы, бэкапы, логи).
    * total - reserved  — сколько осталось необещанного. Ловит ровно тот
      случай, ради которого этот модуль и появился: диски тонкие, места пока
      формально много, но всё оно уже кому-то обещано.

    Когда ВМ заполнят свои диски полностью, обе оценки сходятся.
    """
    unpromised = host_disk_total_gb - reserved_gb
    return max(0.0, round(min(host_disk_free_gb, unpromised), 1))
