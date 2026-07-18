"""Логика запланированных бэкапов.

Планировщик живёт в воркере (отдельный демон-поток) и раз в минуту вызывает
`run_due_backups`. Здесь же — вычисление следующего запуска, само выполнение
бэкапа ВМ/БД и ротация старых копий по политике хранения (retention).

Всё время — UTC (в БД пишется datetime.utcnow()).
"""
import logging
from datetime import datetime, timedelta
from io import BytesIO

logger = logging.getLogger("app.services.scheduled_backups")

DB_BACKUP_BUCKET = "database-backups"


def compute_next_run(frequency: str, hour: int, minute: int, weekday, now: datetime = None) -> datetime:
    """Возвращает ближайший момент запуска строго в будущем относительно now."""
    now = now or datetime.utcnow()
    minute = minute or 0
    hour = hour or 0

    if frequency == "hourly":
        nxt = now.replace(minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(hours=1)
        return nxt

    if frequency == "weekly":
        wd = weekday if weekday is not None else 0
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (wd - now.weekday()) % 7
        nxt += timedelta(days=days_ahead)
        if nxt <= now:
            nxt += timedelta(days=7)
        return nxt

    # daily (и запасной вариант)
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return nxt


# ------------------------------- Бэкап ВМ -----------------------------------

def _backup_timestamp(name: str) -> int:
    """Вытаскивает unix-время из имени бэкапа ВМ ({vm}-backup-{ts})."""
    try:
        return int(name.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 0


def run_vm_backup(k8s, vm_name: str) -> str:
    res = k8s.create_vm_backup(vm_name)
    return res.get("backup_name", "")


def prune_vm_backups(k8s, vm_name: str, retention: int):
    if retention <= 0:
        return
    try:
        backups = k8s.list_vm_backups(vm_name)
    except Exception as e:
        logger.warning(f"prune vm backups: не удалось получить список для {vm_name}: {e}")
        return
    ordered = sorted(backups, key=lambda b: _backup_timestamp(b.get("name", "")), reverse=True)
    for b in ordered[retention:]:
        try:
            k8s.delete_vm_backup(b["name"])
            logger.info(f"Ротация: удалён старый бэкап ВМ {b['name']}")
        except Exception as e:
            logger.warning(f"Ротация: не удалось удалить бэкап {b.get('name')}: {e}")


# ------------------------------- Бэкап БД -----------------------------------

def run_db_backup(k8s, user_db) -> str:
    from app.core.crypto import decrypt_secret
    from app.api.databases import _safe_backup_filename
    from app.api.s3 import get_minio_client

    db_password = decrypt_secret(user_db.db_password)
    dump = k8s.execute_db_backup(
        db_name=user_db.db_name,
        engine=user_db.db_type,
        db_user=user_db.db_user,
        db_password=db_password,
    )
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"backup_{user_db.db_name}_{timestamp}.sql"
    object_name = f"{user_db.db_name}/{_safe_backup_filename(filename)}"

    data = dump.encode("utf-8")
    client = get_minio_client()
    if not client.bucket_exists(DB_BACKUP_BUCKET):
        client.make_bucket(DB_BACKUP_BUCKET)
    client.put_object(
        bucket_name=DB_BACKUP_BUCKET,
        object_name=object_name,
        data=BytesIO(data),
        length=len(data),
        content_type="application/sql",
    )
    return filename


def prune_db_backups(user_db, retention: int):
    if retention <= 0:
        return
    from app.api.s3 import get_minio_client
    try:
        client = get_minio_client()
        prefix = f"{user_db.db_name}/"
        names = [o.object_name for o in client.list_objects(DB_BACKUP_BUCKET, prefix=prefix, recursive=True)]
    except Exception as e:
        logger.warning(f"prune db backups: список для {user_db.db_name} недоступен: {e}")
        return
    # имя содержит временную метку %Y-%m-%d_%H-%M-%S — лексикографически = хронологически
    names.sort(reverse=True)
    for name in names[retention:]:
        try:
            client.remove_object(DB_BACKUP_BUCKET, name)
            logger.info(f"Ротация: удалён старый бэкап БД {name}")
        except Exception as e:
            logger.warning(f"Ротация: не удалось удалить {name}: {e}")


# --------------------------- Тик планировщика -------------------------------

def _execute_one(k8s, db, schedule):
    """Выполняет один бэкап по расписанию и обновляет его статус/время."""
    from app.models.models import VMTask, UserDatabase

    now = datetime.utcnow()
    status = "success"
    try:
        if schedule.target_type == "vm":
            vm = db.query(VMTask).filter(VMTask.id == schedule.target_id).first()
            if not vm:
                raise RuntimeError("ВМ не найдена")
            run_vm_backup(k8s, vm.name)
            prune_vm_backups(k8s, vm.name, schedule.retention)
        elif schedule.target_type == "database":
            udb = db.query(UserDatabase).filter(UserDatabase.id == schedule.target_id).first()
            if not udb:
                raise RuntimeError("База данных не найдена")
            run_db_backup(k8s, udb)
            prune_db_backups(udb, schedule.retention)
        else:
            raise RuntimeError(f"Неизвестный тип цели: {schedule.target_type}")
        logger.info(f"Расписание #{schedule.id} «{schedule.name}»: бэкап выполнен")
    except Exception as e:
        status = f"error: {e}"
        logger.error(f"Расписание #{schedule.id} «{schedule.name}»: ошибка бэкапа: {e}")

    schedule.last_run = now
    schedule.last_status = status
    schedule.next_run = compute_next_run(
        schedule.frequency, schedule.hour, schedule.minute, schedule.weekday, now
    )
    db.commit()


def run_due_backups(k8s):
    """Один тик планировщика: выполняет все расписания, у которых наступил срок."""
    from app.db import SessionLocal
    from app.models.models import BackupSchedule

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        schedules = db.query(BackupSchedule).filter(BackupSchedule.enabled == True).all()  # noqa: E712
        for s in schedules:
            # Первый запуск: если next_run не задан — просто проставляем и ждём срока.
            if s.next_run is None:
                s.next_run = compute_next_run(s.frequency, s.hour, s.minute, s.weekday, now)
                db.commit()
                continue
            if s.next_run <= now:
                _execute_one(k8s, db, s)
    except Exception as e:
        logger.error(f"Ошибка тика планировщика бэкапов: {e}")
    finally:
        db.close()
