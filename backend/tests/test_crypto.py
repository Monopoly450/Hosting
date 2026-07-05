import base64
import hashlib
import importlib

import pytest

from app.core import crypto


def test_roundtrip():
    secret = "super-secret-password-123"
    encrypted = crypto.encrypt_secret(secret)
    assert encrypted != secret
    assert encrypted.startswith(crypto.ENC_PREFIX)
    assert crypto.decrypt_secret(encrypted) == secret


def test_legacy_plaintext_passthrough():
    # Старые записи без префикса возвращаются как есть
    assert crypto.decrypt_secret("old-plaintext-password") == "old-plaintext-password"


def test_empty_values():
    assert crypto.encrypt_secret("") == ""
    assert crypto.encrypt_secret(None) is None
    assert crypto.decrypt_secret("") == ""
    assert crypto.decrypt_secret(None) is None


def test_double_encrypt_is_noop():
    encrypted = crypto.encrypt_secret("value")
    assert crypto.encrypt_secret(encrypted) == encrypted


def test_is_encrypted():
    assert not crypto.is_encrypted("plain")
    assert crypto.is_encrypted(crypto.encrypt_secret("plain"))


def test_wrong_key_raises(monkeypatch):
    encrypted = crypto.encrypt_secret("value")
    monkeypatch.setenv("AEGIS_SECRET_KEY", "another-key")
    importlib.reload(crypto)
    try:
        with pytest.raises(ValueError):
            crypto.decrypt_secret(encrypted)
    finally:
        monkeypatch.setenv("AEGIS_SECRET_KEY", "test-secret-key")
        importlib.reload(crypto)


def test_key_derivation_is_deterministic():
    key1 = crypto._build_key()
    key2 = crypto._build_key()
    assert key1 == key2
    # Ключ пригоден для Fernet: 32 байта в urlsafe base64
    assert len(base64.urlsafe_b64decode(key1)) == 32
