import os
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("app.core.crypto")

# Префикс, по которому отличаем зашифрованные значения от старых plaintext-записей
ENC_PREFIX = "enc:v1:"


def _build_key() -> bytes:
    """Строит ключ Fernet из AEGIS_SECRET_KEY (или из ADMIN_TOKEN для совместимости
    со старыми установками, где AEGIS_SECRET_KEY ещё не задан)."""
    secret = os.getenv("AEGIS_SECRET_KEY") or os.getenv("ADMIN_TOKEN")
    if not secret:
        raise ValueError("Критическая ошибка безопасности: Не задана переменная окружения AEGIS_SECRET_KEY или ADMIN_TOKEN!")
    if secret == "aegis-admin-secret-key-2026":
        raise ValueError("Критическая ошибка безопасности: Использование стандартного ключа 'aegis-admin-secret-key-2026' для шифрования секретов запрещено!")
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), b"aegis-secret-storage-v1", 100_000
    )
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_build_key())


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def encrypt_secret(value: str) -> str:
    """Шифрует секрет для хранения в БД. Пустые и уже зашифрованные значения не трогает."""
    if not value or is_encrypted(value):
        return value
    token = _fernet.encrypt(value.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt_secret(value: str) -> str:
    """Расшифровывает секрет из БД. Значения без префикса считаются
    старыми plaintext-записями и возвращаются как есть."""
    if not value or not is_encrypted(value):
        return value
    token = value[len(ENC_PREFIX):]
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error(
            "Не удалось расшифровать секрет: ключ шифрования не совпадает. "
            "Проверьте, что AEGIS_SECRET_KEY (или ADMIN_TOKEN) не менялся с момента записи."
        )
        raise ValueError("Секрет зашифрован другим ключом (AEGIS_SECRET_KEY изменился)")
