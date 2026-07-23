"""Тесты защит, добавленных по итогам аудита безопасности."""
import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import ssrf
from app.services import registry as reg
from app.services import marketplace as mp
from app.services import domains as dsvc


# ------------------------------- SSRF ---------------------------------------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/auth/users",     # собственное API панели
    "http://localhost:8000/",
    "http://169.254.169.254/latest/meta-data/",  # метаданные облака
    "http://10.0.0.5/internal",
    "http://192.168.1.1/",
    "http://172.16.0.10/",
    "http://[::1]:8000/",
])
def test_internal_targets_are_rejected(url, monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_WEBHOOKS", raising=False)
    with pytest.raises(ValueError):
        ssrf.validate_public_url(url)


@pytest.mark.parametrize("url", ["ftp://example.com", "file:///etc/passwd", "gopher://x", ""])
def test_non_http_schemes_rejected(url):
    with pytest.raises(ValueError):
        ssrf.validate_public_url(url)


def test_public_url_allowed(monkeypatch):
    monkeypatch.setattr(ssrf, "resolve_targets", lambda h: [__import__("ipaddress").ip_address("93.184.216.34")])
    assert ssrf.validate_public_url("https://example.com/hook")


def test_dns_pointing_to_internal_is_rejected(monkeypatch):
    """Имя может быть «внешним», но резолвиться в 127.0.0.1 — проверка по строке
    такое не поймает, поэтому проверяем результат резолва."""
    monkeypatch.setattr(ssrf, "resolve_targets", lambda h: [__import__("ipaddress").ip_address("127.0.0.1")])
    with pytest.raises(ValueError, match="внутренний адрес"):
        ssrf.validate_public_url("https://evil.example.com/hook")


def test_escape_hatch_allows_private(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_WEBHOOKS", "true")
    assert ssrf.validate_public_url("http://10.0.0.5/hook")


# --------------------------- Реестр: имена ----------------------------------

@pytest.mark.parametrize("repo", ["app", "team/app", "my-app", "a.b_c/app"])
def test_valid_repos(repo):
    assert reg.is_valid_repo(repo)


@pytest.mark.parametrize("repo", [
    "../etc/passwd", "app/../../v2/_catalog", "..", "/app", "app/", "App", "app space", "",
])
def test_traversal_and_bad_repos_rejected(repo):
    assert not reg.is_valid_repo(repo)


@pytest.mark.parametrize("tag", ["latest", "v1.2.3", "1_0-beta"])
def test_valid_tags(tag):
    assert reg.is_valid_tag(tag)


@pytest.mark.parametrize("tag", ["../manifests/x", ".hidden", "-lead", "tag/slash", ""])
def test_bad_tags_rejected(tag):
    assert not reg.is_valid_tag(tag)


# ------------------------ Маркетплейс: инъекция в .env ----------------------

def test_newline_in_env_value_is_rejected():
    with pytest.raises(ValueError):
        mp.sanitize_env_value("secret\nEXTRA_VAR=injected")


def test_carriage_return_and_null_rejected():
    for bad in ("a\rb", "a\0b"):
        with pytest.raises(ValueError):
            mp.sanitize_env_value(bad)


def test_resolve_env_rejects_injected_override():
    wp = mp.get_app("wordpress")
    with pytest.raises(ValueError):
        mp.resolve_env(wp, {"DB_PASSWORD": "x\nWORDPRESS_DB_HOST=attacker"})


def test_resolve_env_ignores_keys_outside_schema():
    """Произвольные ключи от пользователя не должны попадать в .env."""
    wp = mp.get_app("wordpress")
    env = mp.resolve_env(wp, {"EVIL": "1"})
    assert "EVIL" not in env


# --------------------- Домены: подтверждение владения -----------------------

def test_challenge_record_name():
    assert dsvc.challenge_record_name("app.example.com") == "_aegis-challenge.app.example.com"


def test_verification_token_is_unique_and_long():
    a, b = dsvc.generate_verification_token(), dsvc.generate_verification_token()
    assert a != b
    assert len(a) > 20


def test_ownership_requires_token():
    ok, detail = dsvc.check_ownership("example.com", None)
    assert ok is False
    assert "токен" in detail


def test_ownership_ok_when_txt_matches(monkeypatch):
    class RD:
        strings = [b"aegis-verify-abc"]
    monkeypatch.setitem(sys.modules, "dns", type(sys)("dns"))
    resolver_mod = type(sys)("dns.resolver")
    resolver_mod.resolve = lambda name, rtype: [RD()]
    monkeypatch.setitem(sys.modules, "dns.resolver", resolver_mod)
    sys.modules["dns"].resolver = resolver_mod

    ok, _ = dsvc.check_ownership("example.com", "aegis-verify-abc")
    assert ok is True


def test_ownership_fails_on_wrong_txt(monkeypatch):
    class RD:
        strings = [b"something-else"]
    monkeypatch.setitem(sys.modules, "dns", type(sys)("dns"))
    resolver_mod = type(sys)("dns.resolver")
    resolver_mod.resolve = lambda name, rtype: [RD()]
    monkeypatch.setitem(sys.modules, "dns.resolver", resolver_mod)
    sys.modules["dns"].resolver = resolver_mod

    ok, _ = dsvc.check_ownership("example.com", "aegis-verify-abc")
    assert ok is False
