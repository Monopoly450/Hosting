"""Проверка пользовательских квот с защитой от гонки.

Проверка «сколько уже занято» и последующая вставка ресурса — две отдельные
операции. Без блокировки два одновременных запроса читают одно и то же
состояние, оба проходят проверку и оба создают ресурс: пользователь с лимитом
в 2 ВМ получает 3. Поэтому перед подсчётом блокируем строку пользователя
(SELECT ... FOR UPDATE) — параллельный запрос того же пользователя подождёт,
пока первый не завершит транзакцию, и увидит уже обновлённое состояние.

Блокировка снимается вместе с commit/rollback вызывающего кода, поэтому
проверять квоту нужно в той же транзакции, в которой создаётся ресурс.
"""
import logging

from fastapi import HTTPException

logger = logging.getLogger("app.core.quotas")


def lock_user_for_quota(db, user):
    """Блокирует строку пользователя до конца транзакции.

    Возвращает актуальную запись User (лимиты могли измениться) либо исходную,
    если блокировка не поддерживается (например, SQLite в тестах).
    """
    from app.models.models import User
    try:
        locked = (db.query(User)
                    .filter(User.id == user.id)
                    .with_for_update()
                    .first())
        return locked or user
    except Exception as e:
        # Не даём проверке квот падать, если БД не умеет FOR UPDATE.
        logger.warning(f"Не удалось заблокировать пользователя {user.id}: {e}")
        db.rollback()
        return user


def current_usage(db, user_id: int) -> dict:
    """Сколько ресурсов уже занято пользователем."""
    from app.models.models import VMTask
    vms = db.query(VMTask).filter(VMTask.owner_id == user_id).all()
    return {
        "vms": len(vms),
        "vcpus": sum(vm.cpu_cores or 0 for vm in vms),
        "ram_mb": sum((vm.memory_gb or 0) * 1024 for vm in vms),
        "storage_gb": sum(vm.disk_gb or 0 for vm in vms),
    }


def enforce_quota(db, user, *, add_vms: int = 1, add_vcpus: int = 0,
                  add_ram_gb: int = 0, add_storage_gb: int = 0):
    """Проверяет, что пользователь укладывается в квоту вместе с новым ресурсом.

    Админ не ограничивается. Вызывать ДО создания ресурса и в той же
    транзакции — иначе блокировка не защитит от гонки.
    """
    if getattr(user, "role", None) == "admin":
        return

    user = lock_user_for_quota(db, user)
    used = current_usage(db, user.id)
    add_ram_mb = add_ram_gb * 1024

    if used["vms"] + add_vms > user.max_vms:
        raise HTTPException(
            status_code=400,
            detail=f"Превышена квота на количество виртуальных машин "
                   f"(лимит: {user.max_vms}, занято: {used['vms']})."
        )
    if used["vcpus"] + add_vcpus > user.max_vcpus:
        raise HTTPException(
            status_code=400,
            detail=f"Превышена квота на ядра процессора "
                   f"(лимит: {user.max_vcpus}, будет занято: {used['vcpus'] + add_vcpus})."
        )
    if used["ram_mb"] + add_ram_mb > user.max_ram_mb:
        raise HTTPException(
            status_code=400,
            detail=f"Превышена квота на объём оперативной памяти "
                   f"(лимит: {user.max_ram_mb} МБ, будет занято: {used['ram_mb'] + add_ram_mb} МБ)."
        )
    if used["storage_gb"] + add_storage_gb > user.max_storage_gb:
        raise HTTPException(
            status_code=400,
            detail=f"Превышена квота на дисковое пространство "
                   f"(лимит: {user.max_storage_gb} ГБ, будет занято: {used['storage_gb'] + add_storage_gb} ГБ)."
        )
