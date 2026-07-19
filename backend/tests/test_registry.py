import os
import sys
import json

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import registry as reg


class FakeClient(reg.RegistryClient):
    """Подменяет сетевой слой заранее заданными ответами по (method, path)."""
    def __init__(self, responses):
        super().__init__("http://reg")
        self.responses = responses
        self.calls = []

    def _request(self, path, method="GET", headers=None):
        self.calls.append((method, path))
        return self.responses[(method, path)]


def test_list_repositories():
    c = FakeClient({("GET", "/v2/_catalog"): (200, {}, json.dumps({"repositories": ["app", "web"]}).encode())})
    assert c.list_repositories() == ["app", "web"]


def test_list_tags_empty():
    c = FakeClient({("GET", "/v2/app/tags/list"): (200, {}, json.dumps({"name": "app", "tags": None}).encode())})
    assert c.list_tags("app") == []


def test_get_digest_reads_header():
    c = FakeClient({("HEAD", "/v2/app/manifests/latest"): (200, {"Docker-Content-Digest": "sha256:abc"}, b"")})
    assert c.get_digest("app", "latest") == "sha256:abc"


def test_delete_tag_resolves_digest_then_deletes():
    c = FakeClient({
        ("HEAD", "/v2/app/manifests/v1"): (200, {"Docker-Content-Digest": "sha256:xyz"}, b""),
        ("DELETE", "/v2/app/manifests/sha256:xyz"): (202, {}, b""),
    })
    assert c.delete_tag("app", "v1") == 202
    assert ("DELETE", "/v2/app/manifests/sha256:xyz") in c.calls


def test_delete_tag_without_digest_raises():
    c = FakeClient({("HEAD", "/v2/app/manifests/v1"): (200, {}, b"")})
    try:
        c.delete_tag("app", "v1")
        assert False, "ожидалась ошибка"
    except RuntimeError:
        pass


def test_push_host_and_base_url():
    assert reg.registry_base_url().startswith("http://localhost:")
    assert ":" in reg.push_host()


def test_registry_status_no_docker():
    class NoDocker:
        def is_available(self): return False
    st = reg.registry_status(NoDocker())
    assert st["docker"] is False and st["running"] is False
    assert "endpoint" in st and "push_host" in st
