"""TOTP (RFC 6238) для двухфакторной аутентификации — на стандартной библиотеке.

Секрет хранится в БД зашифрованным (app.core.crypto). QR-код генерируется как
SVG (data-URI) через qrcode, без Pillow.
"""
import base64
import hashlib
import hmac
import io
import os
import secrets as _secrets
import struct
import time
from urllib.parse import quote, urlencode

ISSUER = "Aegis"


def generate_secret() -> str:
    """Случайный base32-секрет (160 бит)."""
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code_int = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code_int).zfill(digits)


def totp_now(secret_b32: str, t: float = None, step: int = 30, digits: int = 6) -> str:
    if t is None:
        t = time.time()
    return _hotp(secret_b32, int(t // step), digits)


def verify_totp(secret_b32: str, code: str, t: float = None, step: int = 30, digits: int = 6, window: int = 1) -> bool:
    """Проверяет код с допуском ±window шагов (компенсация рассинхронизации часов)."""
    if not code or not secret_b32:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    if t is None:
        t = time.time()
    counter = int(t // step)
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + w, digits), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = ISSUER) -> str:
    """otpauth:// URI для добавления в приложение-аутентификатор.
    Двоеточие между issuer и account в метке оставляем незакодированным (стандарт otpauth)."""
    label = f"{quote(issuer, safe='')}:{quote(account, safe='')}"
    params = urlencode({"secret": secret_b32, "issuer": issuer, "algorithm": "SHA1", "digits": 6, "period": 30})
    return f"otpauth://totp/{label}?{params}"


def qr_svg_data_uri(data: str) -> str:
    """QR-код как data:image/svg+xml (можно вставить прямо в <img src>)."""
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


# ------------------------------ Резервные коды ------------------------------

def generate_backup_codes(n: int = 10) -> list:
    """Список одноразовых резервных кодов вида 'a1b2-c3d4'."""
    codes = []
    for _ in range(n):
        raw = _secrets.token_hex(4)  # 8 hex-символов
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def normalize_backup_code(code: str) -> str:
    return (code or "").strip().lower().replace("-", "").replace(" ", "")


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(normalize_backup_code(code).encode()).hexdigest()
