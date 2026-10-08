"""Выбор пароля, который реально окажется внутри создаваемой ВМ.

Вынесено из worker.py отдельно: воркер при импорте поднимает K8sClient и без
kubeconfig завершает процесс, поэтому логику, которую нужно проверять тестами,
держим в модуле без внешних зависимостей.
"""
import logging

logger = logging.getLogger("app.services.vm_credentials")


def resolve_vm_password(task) -> str:
    """Пароль для Secret с учётными данными ВМ.

    Для деплоя/маркетплейса/клона пароль может быть уже сохранён и вписан в
    custom cloud-init. Используем его и для базовой части объединённого
    документа, и для Secret: новый пароль иначе разойдётся с гостевой ОС.
    Если пользователь явно задаёт другие пароли в YAML, это его настройки,
    и автоматически сгенерированные учётные данные могут не подходить.
    """
    from app.api.vms import generate_random_password

    stored = getattr(task, "vm_password", None)
    if getattr(task, "custom_user_data", None) and stored:
        try:
            from app.core.crypto import decrypt_secret
            return decrypt_secret(stored)
        except Exception as e:
            logger.error(
                f"Не удалось расшифровать пароль ВМ {getattr(task, 'name', '?')}: {e}. "
                "Генерирую новый — SSH-доступ панели к этой ВМ работать не будет."
            )
    return generate_random_password()
