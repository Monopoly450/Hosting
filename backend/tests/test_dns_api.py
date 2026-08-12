"""Автонастройка DNS: панель заводит записи домена сама.

Токен DNS-провайдера и раньше лежал в .env — он нужен Caddy для ACME DNS-01.
Тем же токеном можно создать и TXT подтверждения, и A на этот сервер, и тогда
от пользователя остаётся только ввести домен. Здесь проверяется то, что легко
сломать незаметно: выбор зоны, выбор провайдера и то, что сбой автонастройки
не превращается в исключение на добавлении домена.
"""
import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import dns_api


class FakeProvider(dns_api.DnsProvider):
    name = "fake"
    label = "Fake"

    def __init__(self, zones=("example.com",), fail=None):
        self._zones = list(zones)
        self.fail = fail
        self.calls = []

    def zones(self):
        return self._zones

    def upsert(self, fqdn, rtype, value):
        self.calls.append((rtype, fqdn, value))
        if self.fail:
            raise dns_api.DnsError(self.fail)
        return True, f"{rtype} {fqdn} создана"


# --------------------------------- зоны --------------------------------------

@pytest.mark.parametrize("fqdn,expected", [
    ("example.com", "example.com"),
    ("app.example.com", "example.com"),
    ("a.b.c.example.com", "example.com"),
    ("other.org", None),
])
def test_zone_for_picks_the_owning_zone(fqdn, expected):
    assert FakeProvider().zone_for(fqdn) == expected


def test_zone_for_prefers_the_longest_match():
    """У аккаунта могут быть и example.com, и dev.example.com. Для
    app.dev.example.com верна вторая — иначе запись уйдёт не в ту зону."""
    p = FakeProvider(zones=("example.com", "dev.example.com"))
    assert p.zone_for("app.dev.example.com") == "dev.example.com"
    assert p.zone_for("app.example.com") == "example.com"


def test_zone_lookup_ignores_case_and_trailing_dot():
    p = FakeProvider(zones=("Example.COM",))
    assert p.zone_for("App.Example.com.") == "example.com"


def test_a_similar_but_different_domain_is_not_matched():
    """notexample.com заканчивается на example.com только как строка —
    подставлять для него чужую зону нельзя."""
    assert FakeProvider().zone_for("notexample.com") is None


@pytest.mark.parametrize("fqdn,zone,expected", [
    ("example.com", "example.com", "@"),
    ("app.example.com", "example.com", "app"),
    ("_aegis-challenge.app.example.com", "example.com", "_aegis-challenge.app"),
])
def test_subdomain_split(fqdn, zone, expected):
    assert FakeProvider().subdomain_of(fqdn, zone) == expected


# ------------------------------ выбор провайдера ------------------------------

def test_no_provider_without_tokens(monkeypatch):
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_DNS_API_TOKEN", raising=False)
    assert dns_api.configured_provider() is None
    assert dns_api.automation()["dns_automation"] is False


def test_timeweb_token_selects_timeweb(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_DNS_API_TOKEN", raising=False)
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok")
    p = dns_api.configured_provider()
    assert isinstance(p, dns_api.TimewebDns) and p.token == "tok"


def test_cloudflare_token_selects_cloudflare(monkeypatch):
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_DNS_API_TOKEN", "cf")
    p = dns_api.configured_provider()
    assert isinstance(p, dns_api.CloudflareDns) and p.token == "cf"


def test_choice_is_deterministic_when_both_tokens_are_set(monkeypatch):
    """Порядок зафиксирован намеренно: иначе поведение зависело бы от того,
    в каком порядке перебираются переменные, и «иногда работает» ловилось бы
    только на живом сервере."""
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tw")
    monkeypatch.setenv("CLOUDFLARE_DNS_API_TOKEN", "cf")
    assert dns_api.configured_provider().name == "cloudflare"


def test_automation_reports_the_provider_for_the_ui(monkeypatch):
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_DNS_API_TOKEN", "cf")
    st = dns_api.automation()
    assert st == {"dns_automation": True, "dns_provider": "cloudflare",
                  "dns_provider_label": "Cloudflare"}


# ------------------------------- setup_records --------------------------------

def test_setup_records_creates_both_records(monkeypatch):
    p = FakeProvider()
    monkeypatch.setattr(dns_api, "configured_provider", lambda: p)
    res = dns_api.setup_records("app.example.com", "aegis-verify-xyz", "203.0.113.5")

    assert res["auto"] is True
    assert p.calls == [
        ("TXT", "_aegis-challenge.app.example.com", "aegis-verify-xyz"),
        ("A", "app.example.com", "203.0.113.5"),
    ]


def test_setup_records_without_a_token_is_not_an_error(monkeypatch):
    """Без токена всё работает как раньше — панель показывает записи для
    ручного создания, а не падает."""
    monkeypatch.setattr(dns_api, "configured_provider", lambda: None)
    res = dns_api.setup_records("app.example.com", "tok", "1.2.3.4")
    assert res["auto"] is False and "API-токен" in res["reason"]


def test_provider_failure_is_reported_not_raised(monkeypatch):
    """Автонастройка — удобство поверх ручного пути. Её сбой обязан
    превратиться в понятное сообщение, а не в 500 на добавлении домена."""
    monkeypatch.setattr(dns_api, "configured_provider",
                        lambda: FakeProvider(fail="зона не найдена"))
    res = dns_api.setup_records("app.example.com", "tok", "1.2.3.4")
    assert res["auto"] is False
    assert "зона не найдена" in res["reason"]


def test_network_errors_are_caught_too(monkeypatch):
    class Exploding(FakeProvider):
        def upsert(self, *a):
            raise TimeoutError("read timed out")

    monkeypatch.setattr(dns_api, "configured_provider", lambda: Exploding())
    res = dns_api.setup_records("app.example.com", "tok", "1.2.3.4")
    assert res["auto"] is False and "TimeoutError" in res["reason"]


def test_records_get_a_short_ttl():
    """ACME-проверка идёт сразу после создания TXT: час кеширования у
    резолверов означал бы час ожидания сертификата."""
    assert dns_api.RECORD_TTL <= 300


# --------------------------------- пагинация ----------------------------------
#
# Без неё зона из «второй страницы» просто не находилась бы, и автонастройка
# молча падала бы на «домен не найден среди зон» — при том что домен есть.

class _RecordingCloudflare(dns_api.CloudflareDns):
    PER_PAGE = 2

    def __init__(self, pages):
        super().__init__("tok")
        self.pages = pages
        self.requests = []

    def _call(self, method, path, **kw):
        self.requests.append((method, path, kw.get("params")))
        page = (kw.get("params") or {}).get("page", 1)
        return self.pages[page - 1] if page <= len(self.pages) else []


def test_cloudflare_zones_follow_pagination():
    cf = _RecordingCloudflare([
        [{"name": "a.com"}, {"name": "b.com"}],
        [{"name": "c.com"}],
    ])
    assert cf.zones() == ["a.com", "b.com", "c.com"]


def test_cloudflare_stops_asking_once_a_page_is_short():
    cf = _RecordingCloudflare([[{"name": "a.com"}]])
    cf.zones()
    assert len(cf.requests) == 1


def test_zones_are_fetched_once_and_cached():
    """zone_for() дёргается на каждую запись — второй раз ходить в API незачем."""
    cf = _RecordingCloudflare([[{"name": "a.com"}]])
    cf.zones()
    cf.zones()
    assert len(cf.requests) == 1


class _RecordingTimeweb(dns_api.TimewebDns):
    PER_PAGE = 2

    def __init__(self, pages):
        super().__init__("tok")
        self.pages = pages
        self.offsets = []

    def _call(self, method, path, **kw):
        offset = (kw.get("params") or {}).get("offset", 0)
        self.offsets.append(offset)
        idx = offset // self.PER_PAGE
        return {"domains": self.pages[idx] if idx < len(self.pages) else []}


def test_timeweb_zones_follow_pagination():
    tw = _RecordingTimeweb([
        [{"fqdn": "a.ru"}, {"fqdn": "b.ru"}],
        [{"fqdn": "c.ru"}],
    ])
    assert tw.zones() == ["a.ru", "b.ru", "c.ru"]
    assert tw.offsets == [0, 2]


def test_timeweb_ignores_entries_without_fqdn():
    tw = _RecordingTimeweb([[{"fqdn": "a.ru"}, {}]])
    assert tw.zones() == ["a.ru"]


def test_pagination_is_bounded():
    """Провайдер, всегда отдающий полную страницу, не должен закрутить нас
    в бесконечный цикл внутри HTTP-запроса пользователя."""
    cf = _RecordingCloudflare([[{"name": f"z{i}.com"}, {"name": f"y{i}.com"}]
                               for i in range(dns_api.MAX_PAGES + 5)])
    cf.zones()
    assert len(cf.requests) == dns_api.MAX_PAGES
