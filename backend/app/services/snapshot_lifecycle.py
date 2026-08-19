"""Durable completion of VirtualMachineRestore power-state recovery."""


def restart_vms_after_finished_snapshot_restores(k8s, logger) -> int:
    """Restart completed restore targets without one bad item starving others."""
    completed = 0
    for item in k8s.restores_awaiting_start():
        restore_name = item.get("restore")
        vm_name = item.get("vm")
        if not restore_name or not vm_name:
            logger.warning("Пропускаю неполную запись отката: %r", item)
            continue

        try:
            storage_busy = (
                k8s.active_backup_operation(vm_name)
                or k8s.active_backup_restore_operation(vm_name)
            )
        except Exception as error:
            if getattr(error, "status", None) == 404:
                # Target удалили вместе с ВМ, но VirtualMachineRestore может
                # остаться. Снимаем marker, иначе один такой объект будет
                # падать первым в каждом тике и голодать остальные рестарты.
                logger.warning(
                    "ВМ %s после отката %s уже удалена; снимаю пометку запуска",
                    vm_name,
                    restore_name,
                )
                try:
                    k8s.clear_restart_after_restore(restore_name)
                except Exception as clear_error:
                    logger.error(
                        "Не удалось снять пометку отката %s: %s",
                        restore_name,
                        clear_error,
                    )
                    continue
                completed += 1
            else:
                logger.error(
                    "Не удалось проверить storage-операции ВМ %s: %s",
                    vm_name,
                    error,
                )
            continue

        if storage_busy:
            logger.warning(
                "Откат %s завершён, но ВМ %s занята другой "
                "storage-операцией; повторю позже",
                restore_name,
                vm_name,
            )
            continue

        result_word = "завершился ошибкой" if item.get("failed") else "завершён"
        logger.info(
            "Откат %s %s — возвращаю ВМ %s",
            restore_name,
            result_word,
            vm_name,
        )
        try:
            vm = k8s.get_vm(vm_name)
            already_running = (
                vm.get("status") == "Running"
                or vm.get("desired_state") == "Running"
            )
        except Exception as error:
            if getattr(error, "status", None) == 404:
                logger.warning(
                    "ВМ %s после отката уже удалена; снимаю пометку автозапуска",
                    vm_name,
                )
                already_running = True
            else:
                logger.error(
                    "Не удалось проверить ВМ %s после отката: %s",
                    vm_name,
                    error,
                )
                continue

        if not already_running:
            try:
                k8s.start_vm(vm_name)
            except Exception as error:
                logger.error(
                    "Не удалось включить ВМ %s после отката: %s",
                    vm_name,
                    error,
                )
                continue

        try:
            k8s.clear_restart_after_restore(restore_name)
        except Exception as error:
            logger.error(
                "Не удалось снять пометку автозапуска отката %s: %s",
                restore_name,
                error,
            )
            continue
        completed += 1

    return completed
