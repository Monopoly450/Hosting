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


def ensure_host_capacity(db, *, cpu_cores: int, memory_gb: int, disk_gb: int,
                         k8s=None):
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

    free_cpu = max(0, host["cpu"] - reserved_cpu)
    free_ram = max(0.0, round(host["ram_gb"] - host["ram_used_gb"] - reserved_stopped_ram, 2))

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

    # Диск ВМ — это ровно такой же PVC, как бэкап, сетевой диск или база
    # данных: все они уходят на один и тот же STORAGE_CLASS и конкурируют за
    # одно и то же место. Проверяем через общую функцию, а не по месту, иначе
    # разные создающие эндпоинты снова разойдутся в том, что считают занятым.
    ensure_storage_capacity(db, extra_gb=disk_gb, k8s=k8s)


def available_disk_gb(host_disk_total_gb: float, host_disk_free_gb: float,
                      reserved_gb: float) -> float:
    """Сколько диска можно обещать новому PVC на конкретном бэкенде хранения.

    Берём меньшее из двух оценок, потому что каждая ловит свой случай:

    * host_disk_free_gb — реально свободное место. Ловит ситуацию, когда диск
      занят не виртуалками (образы, бэкапы, логи).
    * total - reserved  — сколько осталось необещанного. Ловит ровно тот
      случай, ради которого этот модуль и появился: диски тонкие, места пока
      формально много, но всё оно уже кому-то обещано.

    Когда данные заполнят обещанное полностью, обе оценки сходятся. Работает
    одинаково для корневого диска хоста и для LVM-пула — им обоим передают
    свои total/free/reserved.
    """
    unpromised = host_disk_total_gb - reserved_gb
    return max(0.0, round(min(host_disk_free_gb, unpromised), 1))


# --------------------------------------------------------------------------
# Место хранения — не только диски ВМ.
#
# STORAGE_CLASS (одна настройка на весь сервер) используется буквально
# ВЕЗДЕ, где создаётся PVC: диск ВМ при создании (app.api.vms), бэкап диска
# (app.core.k8s_client.create_vm_backup), приватная база данных пользователя
# (create_private_db, фиксированно 5 ГБ) и сетевой диск (create_pvc). Все
# четыре конкурируют за одно и то же место — за LVM-пул, если STORAGE_CLASS
# указывает на него, иначе за корневой диск хоста (local-path).
#
# S3 (MinIO) и собственная БД панели (Postgres/MariaDB из docker-compose)
# сюда не входят — это обычные тома Docker на корневом диске хоста, не PVC
# Kubernetes, поэтому они уже покрыты общей проверкой места на диске хоста
# и отдельного учёта не требуют.
# --------------------------------------------------------------------------

def is_lvm_storage_class(name: str) -> bool:
    """Тот же признак, что и в дашборде (app.api.host) — единый источник
    истины, чтобы проверка вместимости и то, что показывает панель, не
    расходились в том, что считать LVM-классом."""
    name = (name or "").lower()
    return "lvm" in name or "vg-" in name


# Имя тома LVM жёстко задано инсталлятором (см. scripts/install-openebs-lvm.sh)
LVM_VG_NAME = "vg-aegis"
LVM_LOOP_IMAGE = "/var/lib/aegis/lvm-storage.img"
LVM_BACKING_MIN_FREE_GB = 5.0


def _parse_lvm_capacity(vgs_output: str, lvs_output: str = "") -> dict | None:
    """Физическая ёмкость VG с учётом свободного места внутри thin-pool."""
    parts = vgs_output.strip().split()
    if len(parts) < 2:
        return None
    total = float(parts[0].replace(",", "."))
    vg_free = float(parts[1].replace(",", "."))
    free_inside_thin_pools = 0.0
    for line in lvs_output.splitlines():
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < 3 or fields[2] != "thin-pool":
            continue
        try:
            pool_size = float(fields[0].replace(",", "."))
            used_percent = float((fields[1] or "0").replace(",", "."))
        except ValueError:
            continue
        free_inside_thin_pools += pool_size * max(
            0.0, 100.0 - used_percent
        ) / 100.0
    return {
        "active": True,
        "total_gb": round(total, 1),
        "free_gb": round(min(total, vg_free + free_inside_thin_pools), 1),
    }


def _lvm_backing_free_gb() -> float:
    """Сколько backing FS sparse-образа можно безопасно отдать новым данным.

    Сам VG видит полный логический размер loop-файла и не знает, осталось ли
    место на файловой системе под его ещё не записанные блоки. Оставляем 5 ГБ
    хосту для журналов/контейнеров; при ошибке чтения fail-closed возвращаем 0.
    """
    import os
    import shutil

    path = LVM_LOOP_IMAGE if os.path.exists(LVM_LOOP_IMAGE) else os.path.dirname(LVM_LOOP_IMAGE)
    try:
        _total, _used, free = shutil.disk_usage(path)
        return max(0.0, free / (1024 ** 3) - LVM_BACKING_MIN_FREE_GB)
    except Exception as e:
        logger.warning(f"read_lvm_pool_gb: backing filesystem недоступна: {e}")
        return 0.0


def read_lvm_pool_gb() -> dict:
    """{'active', 'total_gb', 'free_gb'} для группы томов LVM.

    Читает через nsenter в пространство монтирования хоста — у контейнера
    нет доступа к /dev/mapper и loop-устройствам напрямую (см. host_run в
    app.api.host, та же причина). Без nsenter vgs либо ничего не находит,
    либо падает с ошибкой доступа, и вызывающий код решил бы, что LVM
    неактивен, хотя он просто не смог до него достучаться.
    """
    import subprocess

    def host_lvm(command):
        res = subprocess.run(
            ["nsenter", "--mount=/proc/1/ns/mnt", *command],
            capture_output=True, text=True, timeout=2.0,
        )
        if res.returncode != 0:
            res = subprocess.run(
                command, capture_output=True, text=True, timeout=2.0,
            )
        return res

    try:
        res = host_lvm([
            "vgs", "--units", "g", "--nosuffix", "--noheadings",
            "-o", "vg_size,vg_free", LVM_VG_NAME,
        ])
        if res.returncode == 0:
            # После появления thin-pool vgs считает занятым весь размер
            # самого pool LV, хотя его незаписанная часть всё ещё доступна
            # новым данным и снимкам. Учитываем её через data_percent;
            # иначе после первого PVC панель внезапно показывала почти
            # ноль свободного места и запрещала следующий диск.
            pools = host_lvm([
                "lvs", "--units", "g", "--nosuffix", "--noheadings",
                "--separator", "|", "-o", "lv_size,data_percent,segtype",
                LVM_VG_NAME,
            ])
            parsed = _parse_lvm_capacity(
                res.stdout, pools.stdout if pools.returncode == 0 else ""
            )
            if parsed:
                # PV — sparse loop-файл. LVM может показывать свободные
                # экстенты, которым на backing filesystem уже некуда расти.
                parsed["free_gb"] = round(min(
                    parsed["free_gb"], _lvm_backing_free_gb()
                ), 1)
                return parsed
    except Exception as e:
        logger.warning(f"read_lvm_pool_gb: vgs недоступен: {e}")

    # Файл есть, но VG прочитать нельзя. Его логический размер ничего не говорит
    # ни о занятых блоках, ни о работоспособности пула, поэтому не объявляем весь
    # образ свободным: сохраняем backend=lvm, но fail-closed запрещаем новые PVC.
    try:
        import os
        if os.path.exists(LVM_LOOP_IMAGE):
            total = round(os.path.getsize(LVM_LOOP_IMAGE) / (1024 ** 3), 1)
            return {"active": True, "total_gb": total, "free_gb": 0.0}
    except Exception as e:
        logger.warning(f"read_lvm_pool_gb: не удалось прочитать {LVM_LOOP_IMAGE}: {e}")

    return {"active": False, "total_gb": 0.0, "free_gb": 0.0}


def storage_backend_totals() -> dict:
    """{'backend', 'total_gb', 'free_gb'} — куда РЕАЛЬНО уйдёт новый PVC при
    текущем значении STORAGE_CLASS: в LVM-пул или на корневой диск хоста."""
    from app.core.config import settings

    if is_lvm_storage_class(settings.STORAGE_CLASS):
        lvm = read_lvm_pool_gb()
        if lvm["active"]:
            return {"backend": "lvm", "total_gb": lvm["total_gb"], "free_gb": lvm["free_gb"]}
        logger.warning(
            f"STORAGE_CLASS={settings.STORAGE_CLASS!r} указывает на LVM, но "
            f"группа томов {LVM_VG_NAME} не отвечает — запрещаю новые PVC")
        return {"backend": "lvm", "total_gb": 0.0, "free_gb": 0.0}

    host = host_totals()
    return {"backend": "local", "total_gb": host["disk_gb"], "free_gb": host["disk_free_gb"]}


def known_storage_reservations_gb(db, k8s=None, *, require_backups: bool = False) -> float:
    """Сколько ГБ уже обещано на активном бэкенде хранения (см.
    storage_backend_totals): диски ВМ + сетевые диски + базы данных, и —
    если передан k8s-клиент — бэкапы. Бэкапы требуют обращения к
    Kubernetes (для их размеров нет отдельной таблицы в БД), поэтому
    считаются, только когда клиент передан явно, а не при каждой проверке."""
    from app.models.models import VMTask, UserVolume, UserDatabase
    from app.core.k8s_client import DB_PVC_SIZE_GB

    total = sum(vm.disk_gb or 0 for vm in db.query(VMTask).all())
    total += sum(v.size_gb or 0 for v in db.query(UserVolume).all())
    total += db.query(UserDatabase).count() * DB_PVC_SIZE_GB

    if k8s is not None:
        total += backups_total_gb(k8s, strict=require_backups)

    return float(total)


def backups_total_gb(k8s, *, strict: bool = False) -> float:
    """Суммарный размер дополнительных полных клонов дисков ВМ.

    Это постоянные backup DataVolume и временные staged-restore DataVolume.
    Последние живут рядом со старым рабочим диском до безопасного switch и
    потому тоже должны занимать часть логического promise ceiling.
    """
    try:
        dvs = k8s.custom_api.list_cluster_custom_object(
            group="cdi.kubevirt.io", version="v1beta1", plural="datavolumes")
    except Exception as e:
        logger.warning(f"backups_total_gb: не удалось получить список DataVolume: {e}")
        if strict:
            raise
        return 0.0

    total = 0.0
    for dv in dvs.get("items", []):
        labels = dv.get("metadata", {}).get("labels") or {}
        if not (
            "hosting.antigravity.io/backup-source" in labels
            or "hosting.antigravity.io/restore-operation" in labels
        ):
            continue
        size_str = (dv.get("spec", {}).get("storage", {})
                    .get("resources", {}).get("requests", {}).get("storage", "0Gi"))
        try:
            if size_str.endswith("Gi"):
                total += float(size_str[:-2])
            elif size_str.endswith("Mi"):
                total += float(size_str[:-2]) / 1024
        except ValueError:
            pass
    return total


def ensure_storage_capacity(db, *, extra_gb: float, k8s=None):
    """Не даёт занять на активном бэкенде хранения больше, чем там есть.

    Общая проверка для ЛЮБОГО нового PVC: диска ВМ, бэкапа, сетевого диска,
    базы данных. Раньше каждый из этих путей либо не проверял место вообще
    (бэкапы, базы данных), либо проверял его сам и неправильно: сетевые
    диски сверялись с LVM через vgs БЕЗ nsenter (внутри контейнера это либо
    падает, либо не находит группу томов — проверка молча не срабатывала),
    а диск ВМ проверялся только по свободному месту на корневом диске хоста,
    даже если PVC на самом деле уходит в отдельный, куда более маленький
    LVM-пул.
    """
    from fastapi import HTTPException

    backend = storage_backend_totals()
    try:
        reserved = known_storage_reservations_gb(
            db, k8s=k8s, require_backups=k8s is not None
        )
    except Exception as e:
        logger.warning(f"ensure_storage_capacity: backup reservations недоступны: {e}")
        raise HTTPException(
            status_code=503,
            detail="Не удалось проверить занятое место бэкапами в Kubernetes; создание PVC временно остановлено.",
        )
    free = available_disk_gb(backend["total_gb"], backend["free_gb"], reserved)

    if extra_gb > free:
        where = "LVM-пуле" if backend["backend"] == "lvm" else "локальном диске хоста"
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно места на {where}. Запрошено: {extra_gb} ГБ, "
                   f"доступно: {free} ГБ (всего: {backend['total_gb']} ГБ, "
                   f"уже зарезервировано: {round(reserved, 1)} ГБ).")


def ensure_any_storage_headroom(db, k8s=None):
    """Для операций без заранее известного размера — снимков ВМ.

    В отличие от бэкапа (полный клон PVC, размер известен заранее),
    VirtualMachineSnapshot — дифференциальный объект: он растёт по мере
    изменений на диске уже ПОСЛЕ создания снимка, и сколько места ему
    понадобится, нельзя знать в момент создания. Резервировать здесь нечего,
    но пул, где уже физически не осталось места, — самостоятельная причина
    отказать: снимку будет некуда расти, и он либо не создастся, либо
    испортит данные вместо честного отказа.

    Не выражается через ensure_storage_capacity(extra_gb=0): запрос «0
    дополнительных ГБ» математически влезает в любое неотрицательное
    свободное место, включая ровно ноль, — это не тот вопрос, который здесь
    нужен.
    """
    from fastapi import HTTPException

    backend = storage_backend_totals()
    try:
        reserved = known_storage_reservations_gb(
            db, k8s=k8s, require_backups=k8s is not None
        )
    except Exception as e:
        logger.warning(f"ensure_any_storage_headroom: backup reservations недоступны: {e}")
        raise HTTPException(
            status_code=503,
            detail="Не удалось проверить занятое место бэкапами в Kubernetes; создание снимка временно остановлено.",
        )
    free = available_disk_gb(backend["total_gb"], backend["free_gb"], reserved)
    if free <= 0:
        where = "LVM-пуле" if backend["backend"] == "lvm" else "локальном диске хоста"
        raise HTTPException(
            status_code=400,
            detail=f"На {where} не осталось свободного места (всего: {backend['total_gb']} ГБ, "
                   f"уже зарезервировано: {round(reserved, 1)} ГБ). Снимку будет некуда расти.")
