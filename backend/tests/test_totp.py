import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import totp


def test_totp_roundtrip():
    secret = totp.generate_secret()
    code = totp.totp_now(secret)
    assert totp.verify_totp(secret, code) is True


def test_totp_rejects_wrong_code():
    secret = totp.generate_secret()
    assert totp.verify_totp(secret, "000000") is False
    assert totp.verify_totp(secret, "") is False
    assert totp.verify_totp(secret, "abcdef") is False


def test_totp_window_tolerates_adjacent_step():
    secret = totp.generate_secret()
    # код предыдущего 30-секундного окна должен приниматься (window=1)
    prev = totp.totp_now(secret, t=1000)
    assert totp.verify_totp(secret, prev, t=1000 + 30) is True
    # а код двумя окнами ранее — уже нет
    assert totp.verify_totp(secret, prev, t=1000 + 90) is False


def test_totp_matches_rfc_test_vector():
    # RFC 4226: секрет "12345678901234567890" (ASCII) в base32,
    # счётчик 1 -> HOTP = 287082 (известный вектор). При step=30 это t=59с.
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.totp_now(secret, t=59) == "287082"


def test_backup_code_hash_normalizes():
    codes = totp.generate_backup_codes(5)
    assert len(codes) == 5
    c = codes[0]
    # регистр и дефисы не влияют на хэш
    assert totp.hash_backup_code(c) == totp.hash_backup_code(c.upper().replace("-", ""))
    assert totp.hash_backup_code(c) != totp.hash_backup_code("ffff-ffff")


def test_provisioning_uri_format():
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "admin")
    assert uri.startswith("otpauth://totp/Aegis:admin?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=Aegis" in uri


def test_qr_svg_data_uri():
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "admin")
    data = totp.qr_svg_data_uri(uri)
    assert data.startswith("data:image/svg+xml;base64,")
