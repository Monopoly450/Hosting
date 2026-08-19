"""Завершение offline-бэкапа виртуальной машины.

CDI не может клонировать диск, пока его держит virt-launcher, поэтому
запущенную ВМ панель гасит перед созданием DataVolume. Намерение вернуть
ВМ хранится в annotation DataVolume и поэтому не теряется при перезапуске
воркера. Здесь находится один тестируемый тик этого жизненного цикла;
сам периодический цикл живёт в worker.py.
"""


def restart_vms_after_finished_backups(k8s, logger) -> int:
    """Включает ВМ после terminal DataVolume и возвращает число завершённых.

    Пометка снимается только после успешного запуска. Если patch не удался,
    следующий тик сначала увидит, что ВМ уже работает, и только повторит
    снятие annotation: start-subresource KubeVirt сам по себе не идемпотентен.
    """
    completed = 0
    for item in k8s.backups_awaiting_start():
        backup_name = item.get("backup")
        vm_name = item.get("vm")
        phase = item.get("phase")
        backup_exists = item.get("backup_exists", True)
        cancel_backup = item.get("cancel_backup", False)
        source_pvc = item.get("source_pvc")
        restart_vm = item.get("restart_vm", True)
        if not backup_name or not vm_name:
            logger.warning(
                "Пропускаю неполную запись завершённого бэкапа: %r",
                item,
            )
            continue

        logger.info(
            "Бэкап %s перешёл в %s — завершаю offline-операцию ВМ %s",
            backup_name,
            phase or "terminal",
            vm_name,
        )
        if cancel_backup:
            logger.error(
                "Бэкап %s превысил предельное время — отменяю clone перед "
                "запуском ВМ %s",
                backup_name,
                vm_name,
            )
            try:
                k8s.cancel_backup_datavolume(backup_name)
                backup_exists = False
            except Exception as error:
                logger.error(
                    "Не удалось отменить зависший бэкап %s: %s",
                    backup_name,
                    error,
                )
                continue

        if restart_vm:
            already_running = False
            vm_missing = False
            try:
                already_running = k8s.get_vm(vm_name).get("status") == "Running"
            except Exception as error:
                # Удалённую вместе с её бэкапом ВМ уже некуда включать. Снимаем
                # пометку, чтобы остаток DataVolume можно было удалить штатно.
                if getattr(error, "status", None) == 404:
                    logger.warning(
                        "ВМ %s для бэкапа %s уже удалена; снимаю пометку запуска",
                        vm_name,
                        backup_name,
                    )
                    vm_missing = True
                else:
                    logger.warning(
                        "Не удалось проверить состояние ВМ %s: %s",
                        vm_name,
                        error,
                    )
                    continue

            # Проверяем source PVC только перед фактическим start. Если start
            # уже сработал, а ответ/следующий patch потерялся, сама ВМ держит
            # этот PVC, и ожидание до проверки Running создало бы вечный цикл.
            if not already_running and not vm_missing:
                if source_pvc:
                    try:
                        source_free = k8s.wait_for_pvc_unused(source_pvc)
                    except Exception as error:
                        logger.error(
                            "Не удалось проверить диск %s перед запуском ВМ: %s",
                            source_pvc,
                            error,
                        )
                        continue
                    if not source_free:
                        logger.error(
                            "Диск %s всё ещё используется после бэкапа %s",
                            source_pvc,
                            backup_name,
                        )
                        continue
                try:
                    k8s.start_vm(vm_name)
                except Exception as error:
                    logger.error(
                        "Не удалось включить ВМ %s после бэкапа %s: %s",
                        vm_name,
                        backup_name,
                        error,
                    )
                    continue
        elif source_pvc:
            # Изначально выключенную ВМ включать не надо, но lock можно снять
            # только после ухода clone-pod. Иначе пользователь успеет нажать
            # Start, пока CDI всё ещё держит исходный диск.
            try:
                source_free = k8s.wait_for_pvc_unused(source_pvc)
            except Exception as error:
                logger.error(
                    "Не удалось проверить диск %s после бэкапа %s: %s",
                    source_pvc,
                    backup_name,
                    error,
                )
                continue
            if not source_free:
                logger.error(
                    "Диск %s всё ещё используется после бэкапа %s",
                    source_pvc,
                    backup_name,
                )
                continue

        if backup_exists:
            try:
                k8s.clear_restart_after_backup(backup_name)
            except Exception as error:
                if getattr(error, "status", None) != 404:
                    logger.error(
                        "Offline-операция ВМ %s завершена, но не удалось "
                        "снять пометку с бэкапа %s: %s",
                        vm_name,
                        backup_name,
                        error,
                    )
                    continue
        try:
            k8s.clear_backup_operation(vm_name, backup_name)
        except Exception as error:
            # Для удалённой ВМ marker уже исчез вместе с объектом.
            if getattr(error, "status", None) != 404:
                logger.error(
                    "Не удалось снять marker offline-бэкапа с ВМ %s: %s",
                    vm_name,
                    error,
                )
                continue
        completed += 1

    return completed


def finish_backup_restores(k8s, logger) -> int:
    """Завершает durable restore-lock после terminal target DataVolume."""
    completed = 0
    for item in k8s.backup_restores_awaiting_finish():
        operation = item.get("operation")
        vm_name = item.get("vm")
        phase = item.get("phase")
        if not operation or not vm_name:
            continue

        try:
            k8s.finish_backup_restore(item)
        except Exception as error:
            logger.error(
                "Не удалось завершить restore %s ВМ %s (phase=%s): %s",
                operation,
                vm_name,
                phase,
                error,
            )
            continue
        completed += 1
    return completed
