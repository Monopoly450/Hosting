import base64
import os
import sys

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.auth import secure_eq
from app.services import registry as reg


# ------------------------- constant-time compare ----------------------------

def test_secure_eq_matches():
    assert secure_eq("abc", "abc") is True


def test_secure_eq_mismatch():
    assert secure_eq("abc", "abd") is False
    assert secure_eq("abc", "abcd") is False


def test_secure_eq_none_or_wrong_type():
    assert secure_eq(None, "abc") is False
    assert secure_eq("abc", None) is False
    assert secure_eq(b"abc", "abc") is False


# ---------------------------- registry htpasswd -----------------------------

def test_htpasswd_entry_is_bcrypt_and_verifiable():
    import bcrypt
    line = reg.htpasswd_entry("aegis", "s3cret")
    user, _, hashed = line.partition(":")
    assert user == "aegis"
    assert hashed.startswith("$2")  # bcrypt
    assert bcrypt.checkpw(b"s3cret", hashed.encode())
    assert not bcrypt.checkpw(b"wrong", hashed.encode())


# --------------------------- credential storage -----------------------------

def test_credentials_created_and_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path))
    assert reg.load_credentials() is None          # ещё не создано
    c1 = reg.load_or_create_credentials()
    assert c1["user"] == "aegis"
    assert len(c1["password"]) >= 32
    c2 = reg.load_or_create_credentials()          # повторный вызов — те же данные
    assert c1 == c2
    assert reg.load_credentials() == c1            # читается с диска


def test_credentials_file_is_encrypted(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path))
    creds = reg.load_or_create_credentials()
    raw = open(reg._creds_path()).read()
    assert creds["password"] not in raw           # пароль на диске не в открытом виде


# ------------------------- client basic auth --------------------------------

def test_client_sends_basic_auth_header():
    c = reg.RegistryClient(auth=("aegis", "pw"))
    hdr = c._auth_header()
    assert hdr["Authorization"].startswith("Basic ")
    decoded = base64.b64decode(hdr["Authorization"].split(" ", 1)[1]).decode()
    assert decoded == "aegis:pw"


def test_client_without_auth_sends_no_header():
    assert reg.RegistryClient()._auth_header() == {}


def test_client_request_includes_auth(monkeypatch):
    captured = {}

    class FakeResp:
        status = 200
        headers = {}
        def read(self): return b'{"repositories": ["app"]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=10):
        captured["auth"] = req.headers.get("Authorization")
        return FakeResp()

    monkeypatch.setattr(reg.urllib.request, "urlopen", fake_urlopen)
    c = reg.RegistryClient(auth=("aegis", "pw"))
    assert c.list_repositories() == ["app"]
    assert captured["auth"].startswith("Basic ")
