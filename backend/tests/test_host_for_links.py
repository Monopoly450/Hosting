"""Ссылки должны указывать на тот адрес, по которому открыта панель.

Одного верного адреса не существует: домены и Let's Encrypt требуют публичный
(AEGIS_HOST_IP), но по нему из локальной сети часто не пройти — NAT-петля
поддерживается далеко не везде. Пока адрес брался из общей настройки, человек,
работающий из локальной сети, получал ссылку вида 185.177.219.140:28009, которая
у него не открывалась.
"""
import os
import sys
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")
os.environ.setdefault("IMAGES_DIR", "/tmp/aegis-test-images")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.netutils import host_for_links


def request(host=None, forwarded=None):
    headers = {}
    if forwarded:
        headers["x-forwarded-host"] = forwarded
    return types.SimpleNamespace(
        headers=headers,
        url=types.SimpleNamespace(hostname=host),
    )


def test_uses_the_address_the_panel_was_opened_on():
    """Работа из локальной сети — локальные ссылки."""
    assert host_for_links(request(host="192.168.31.10")) == "192.168.31.10"


def test_uses_domain_when_opened_by_domain():
    assert host_for_links(request(host="panel.example.com")) == "panel.example.com"


def test_forwarded_host_wins_because_panel_sits_behind_nginx():
    r = request(host="127.0.0.1", forwarded="panel.example.com")
    assert host_for_links(r) == "panel.example.com"


def test_forwarded_host_port_is_stripped():
    r = request(host="127.0.0.1", forwarded="192.168.31.10:8443")
    assert host_for_links(r) == "192.168.31.10"


def test_first_value_of_a_forwarded_chain_is_used():
    r = request(host="127.0.0.1", forwarded="panel.example.com, proxy.internal")
    assert host_for_links(r) == "panel.example.com"


@pytest.mark.parametrize("loopback", ["localhost", "127.0.0.1", "::1"])
def test_loopback_falls_back_to_detected_address(loopback, monkeypatch):
    """Ссылка на localhost бесполезна: её открывают на другой машине."""
    monkeypatch.setenv("AEGIS_HOST_IP", "203.0.113.9")
    assert host_for_links(request(host=loopback)) == "203.0.113.9"


def test_without_request_uses_configured_address(monkeypatch):
    """Фоновые задачи запроса не имеют — там остаётся общая настройка."""
    monkeypatch.setenv("AEGIS_HOST_IP", "203.0.113.9")
    assert host_for_links(None) == "203.0.113.9"


def test_endpoints_pass_the_request_through():
    """Ссылки собираются в _enrich, поэтому request обязан до него доходить."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "deployments.py",
    )
    with open(path, encoding="utf-8") as f:
        src = f.read()

    assert "def list_deployments(request: Request" in src
    assert "def create_deployment(req: DeploymentCreate, request: Request" in src
    assert "host_for_links(request)" in src
    assert "_enrich(d, owner.username if owner else \"—\", request)" in src


def test_marketplace_builds_public_url_from_request():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "marketplace.py",
    )
    with open(path, encoding="utf-8") as f:
        src = f.read()

    assert "host_for_links(request)" in src
    assert "add_public_url(env, default_host()" not in src, (
        "PUBLIC_URL должен собираться по адресу запроса, а не по общей настройке"
    )


def test_registry_uses_request_host_too():
    """docker push на публичный IP из локальной сети обычно не проходит."""
    from app.services.registry import push_host, REGISTRY_PORT

    assert push_host("192.168.31.10") == f"192.168.31.10:{REGISTRY_PORT}"


def test_registry_falls_back_without_host(monkeypatch):
    monkeypatch.setenv("AEGIS_HOST_IP", "203.0.113.9")
    from app.services.registry import push_host, REGISTRY_PORT

    assert push_host() == f"203.0.113.9:{REGISTRY_PORT}"


def test_registry_endpoints_pass_the_request():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "registry.py",
    )
    with open(path, encoding="utf-8") as f:
        src = f.read()

    assert "def info(request: Request)" in src
    assert "def status(request: Request" in src
    assert "host_for_links(request)" in src
    assert "reg.push_host()" not in src, "адрес push должен зависеть от запроса"


def test_domains_show_the_address_the_panel_was_opened_on():
    """Подсказка «A @ → ...» показывает адрес этого сервера, а не AEGIS_HOST_IP.

    Раньше здесь стоял detect_host_ip(), который в первую очередь читает
    AEGIS_HOST_IP: однажды заданная переменная показывалась и тогда, когда
    панель открыта по совсем другому адресу. Публичность адреса проверяется
    отдельно — см. тест ниже про предупреждение.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "domains.py",
    )
    with open(path, encoding="utf-8") as f:
        src = f.read()

    assert "host_for_links(request)" in src


def test_domains_verify_against_the_same_address_it_shows():
    """DNS сверяется с тем же адресом, который показан пользователю.

    Если подсказка и проверка расходятся, пользователь пропишет A-запись ровно
    так, как ему показали, а верификация всё равно не пройдёт.

    Проверка идёт по цепочке: API берёт адрес из host_for_links(request) и
    отдаёт его сервису, а сервис сверяет с ним A-запись. Сама сверка живёт в
    сервисе, потому что тем же кодом пользуется фоновая доперепроверка
    доменов в воркере (autoverify_tick), у которой запроса нет вовсе.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "app", "api", "domains.py"), encoding="utf-8") as f:
        api_src = f.read()
    with open(os.path.join(root, "app", "services", "domains.py"), encoding="utf-8") as f:
        svc_src = f.read()

    assert "expected = host_for_links(request)" in api_src
    assert "verify_domain_row(db, dom, expected)" in api_src
    assert '"expected_ip": expected' in api_src
    assert "check_dns(dom.domain, expected_ip=expected_ip)" in svc_src
