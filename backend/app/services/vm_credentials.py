"""Выбор пароля, который реально окажется внутри создаваемой ВМ.

Вынесено из worker.py отдельно: воркер при импорте поднимает K8sClient и без
kubeconfig завершает процесс, поэтому логику, которую нужно проверять тестами,
держим в модуле без внешних зависимостей.
"""
import logging

logger = logging.getLogger("app.services.vm_credentials")


def resolve_vm_password(task) -> str:
    """Пароль для Secret с учётными данными ВМ.

    Когда cloud-init задан извне (деплой, маркетплейс, клон), пароль в него уже
    вписан, а `generate_linux_manifest` переданный аргумент игнорирует. Если в
    этом случае сгенерировать новый пароль, он уйдёт в Secret и разойдётся с
    тем, что стоит в системе, — панель перестанет заходить в ВМ по SSH (логи
    сборки, веб-терминал, подсказка подключения).
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
