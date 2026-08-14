import os
import sys
import types

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docker.errors

from app.services import domains as d


# ------------------------------ Валидация -----------------------------------

def test_valid_domains():
    for name in ("example.com", "app.example.com", "a-b.example.co.uk", "x1.test.io"):
        assert d.is_valid_domain(name), name


def test_invalid_domains():
    for name in ("", "localhost", "no-tld", "-bad.example.com", "bad-.example.com",
                 "sp ace.com", "a" * 64 + ".com", "точка.рф "):
        assert not d.is_valid_domain(name), name


# ---------------------------- Генерация конфига -----------------------------

def test_caddyfile_has_site_block_per_domain():
    cfg = d.build_caddyfile([
        {"domain": "b.example.com", "upstream": "192.168.100.12:2368"},
        {"domain": "a.example.com", "upstream": "192.168.100.11:8080"},
    ])
    assert "a.example.com {" in cfg
    assert "b.example.com {" in cfg
    assert "reverse_proxy 192.168.100.11:8080" in cfg
    assert "reverse_proxy 192.168.100.12:2368" in cfg
    # домены отсортированы — конфиг стабилен между перегенерациями
    assert cfg.index("a.example.com") < cfg.index("b.example.com")


def test_caddyfile_includes_acme_email_when_set():
    cfg = d.build_caddyfile([{"domain": "a.example.com", "upstream": "1.2.3.4:80"}], email="me@example.com")
    assert "email me@example.com" in cfg


def test_empty_caddyfile_stub_does_not_collide_with_the_panels_own_port():
    """Реальный баг: заглушка «нет доменов» слушала :8080 — тот же порт,
    на котором сама панель отдаёт себя (frontend/nginx.conf). Caddy работает
    в network_mode host, поэтому кто из двух стартовал раньше, тот и занимал
    порт: второй не мог забиндиться и падал. На живом сервере это выглядело
    так — вместо панели браузер показывал заглушку Caddy."""
    cfg = d.build_caddyfile([])
    assert ":8080 {" not in cfg
    assert ":8443 {" not in cfg
    assert "домены не настроены" in cfg


def test_caddyfile_without_email_has_no_global_block():
    cfg = d.build_caddyfile([{"domain": "a.example.com", "upstream": "1.2.3.4:80"}])
    assert "email" not in cfg


def test_caddyfile_uses_dns01_when_entry_carries_a_dns_token():
    """Домен панели (см. panel_entry) не проходит обычный HTTP-01 — приватный
    IP недостижим извне. Такая запись должна получить блок dns вместо
    молчаливого падения на обычный (заведомо неудачный) ACME."""
    cfg = d.build_caddyfile([
        {"domain": "home.example.com", "upstream": "127.0.0.1:8081", "dns_token": "tok-123"},
    ])
    assert "tls {" in cfg
    assert "dns timeweb tok-123" in cfg
    assert "reverse_proxy 127.0.0.1:8081" in cfg


def test_caddyfile_dns01_block_avoids_the_propagation_race():
    """Инцидент на живом сервере: без задержки Let's Encrypt спрашивал
    TXT-запись раньше, чем она реально разошлась у Timeweb (каждая ACME-
    попытка запрашивает новый токен), а проверка НАПРЯМУЮ через авторитетные
    NS домена подвисала на прямом TCP:53 наружу и падала по таймауту.

    30 секунд оказалось мало: домен n8n получил NXDOMAIN на
    _acme-challenge три попытки подряд, а соседний уложился за 36 секунд —
    впритык. Задержка отодвигает только первую проверку, поэтому увеличена
    с запасом."""
    cfg = d.build_caddyfile([
        {"domain": "home.example.com", "upstream": "127.0.0.1:8081", "dns_token": "tok-123"},
    ])
    assert f"propagation_delay {d.ACME_PROPAGATION_DELAY}" in cfg
    assert f"propagation_timeout {d.ACME_PROPAGATION_TIMEOUT}" in cfg
    assert "resolvers 1.1.1.1 8.8.8.8" in cfg

    # Задержка должна быть заметно больше тех 30 секунд, на которых обожглись.
    assert d.ACME_PROPAGATION_DELAY.endswith("m")


def test_caddyfile_plain_entry_has_no_dns_block():
    cfg = d.build_caddyfile([{"domain": "a.example.com", "upstream": "1.2.3.4:80"}])
    assert "tls {" not in cfg
    assert "dns timeweb" not in cfg


# ------------------------------ Домен панели ---------------------------------

def test_panel_entry_absent_without_env(monkeypatch):
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    assert d.panel_entry() is None


def test_panel_entry_absent_with_only_domain_set(monkeypatch):
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    assert d.panel_entry() is None


def test_panel_entry_present_when_both_env_vars_set(monkeypatch):
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")
    entry = d.panel_entry()
    assert entry == {
        "domain": "home.example.com",
        "upstream": d.PANEL_UPSTREAM,
        "dns_token": "tok-abc",
    }


def test_build_entries_includes_panel_domain_even_with_no_db_domains(monkeypatch):
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")
    entries = d.build_entries(FakeDb(), object())
    assert entries == [{
        "domain": "home.example.com",
        "upstream": d.PANEL_UPSTREAM,
        "dns_token": "tok-abc",
    }]


# --------------------------- Домены прочих сервисов ---------------------------
#
# Не только у панели приватный IP — почта (Roundcube) и консоль MinIO живут
# на том же хосте и упираются в то же самое ограничение HTTP-01/TLS-ALPN-01.

def test_mail_and_storage_domain_absent_without_env(monkeypatch):
    monkeypatch.delenv("MAIL_DOMAIN", raising=False)
    monkeypatch.delenv("STORAGE_DOMAIN", raising=False)
    assert d.mail_domain() == "" and d.storage_domain() == ""


def test_system_domain_entries_empty_when_nothing_configured(monkeypatch):
    for var in ("PANEL_DOMAIN", "MAIL_DOMAIN", "STORAGE_DOMAIN", "TIMEWEB_DNS_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert d.system_domain_entries() == []


def test_system_domain_entries_covers_mail_and_storage_independently_of_panel(monkeypatch):
    """Можно привязать домен к почте/хранилищу, даже не трогая панель —
    каждая переменная работает сама по себе."""
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.setenv("MAIL_DOMAIN", "mail.example.com")
    monkeypatch.setenv("STORAGE_DOMAIN", "storage.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")

    entries = d.system_domain_entries()

    assert entries == [
        {"domain": "mail.example.com", "upstream": d.MAIL_UPSTREAM, "dns_token": "tok-abc"},
        {"domain": "storage.example.com", "upstream": d.STORAGE_UPSTREAM, "dns_token": "tok-abc"},
    ]


def test_system_domain_entries_covers_all_three_together(monkeypatch):
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.setenv("MAIL_DOMAIN", "mail.example.com")
    monkeypatch.setenv("STORAGE_DOMAIN", "storage.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")

    entries = d.system_domain_entries()

    assert entries == [
        {"domain": "home.example.com", "upstream": d.PANEL_UPSTREAM, "dns_token": "tok-abc"},
        {"domain": "mail.example.com", "upstream": d.MAIL_UPSTREAM, "dns_token": "tok-abc"},
        {"domain": "storage.example.com", "upstream": d.STORAGE_UPSTREAM, "dns_token": "tok-abc"},
    ]


def test_system_domain_entries_needs_a_token_even_if_domains_are_set(monkeypatch):
    monkeypatch.setenv("MAIL_DOMAIN", "mail.example.com")
    monkeypatch.setenv("STORAGE_DOMAIN", "storage.example.com")
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    assert d.system_domain_entries() == []


def test_build_entries_includes_mail_and_storage_domains(monkeypatch):
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.setenv("MAIL_DOMAIN", "mail.example.com")
    monkeypatch.setenv("STORAGE_DOMAIN", "storage.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")
    entries = d.build_entries(FakeDb(), object())
    assert entries == [
        {"domain": "mail.example.com", "upstream": d.MAIL_UPSTREAM, "dns_token": "tok-abc"},
        {"domain": "storage.example.com", "upstream": d.STORAGE_UPSTREAM, "dns_token": "tok-abc"},
    ]


class _FakeDomainRow:
    def __init__(self, domain):
        self.domain = domain


class _DomainOnlyQuery:
    def __init__(self, items):
        self._items = items

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._items


class _DomainOnlyDb:
    """Отдаёт заданные домены на любой query() — resolve_upstream (который
    полез бы за AppDeployment/VMTask) в этих тестах подменяется отдельно,
    так что глубже мокать БД не нужно."""

    def __init__(self, domains):
        self._domains = domains

    def query(self, model):
        return _DomainOnlyQuery(self._domains)


def test_build_entries_gives_dns01_to_customer_domains_on_a_private_host(monkeypatch):
    """Живой инцидент: клиентский домен указывал на тот же приватный IP, что
    и панель — Let's Encrypt в принципе не признаёт приватный адрес валидным
    для HTTP-01/TLS-ALPN-01 ("no valid A records found"). Клиентские домены
    на приватном хосте должны получать DNS-01 точно так же, как домен самой
    панели (см. panel_entry)."""
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.setattr(d, "is_private_host_ip", lambda *a, **k: True)
    monkeypatch.setattr(d, "resolve_upstream", lambda db, k8s, dom: ("10.0.0.9:80", None))

    db = _DomainOnlyDb([_FakeDomainRow("app.example.com")])
    entries = d.build_entries(db, object())

    assert entries == [{
        "domain": "app.example.com",
        "upstream": "10.0.0.9:80",
        "dns_token": "tok-abc",
    }]


def test_build_entries_leaves_customer_domains_alone_on_a_public_host(monkeypatch):
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.setattr(d, "is_private_host_ip", lambda *a, **k: False)
    monkeypatch.setattr(d, "resolve_upstream", lambda db, k8s, dom: ("203.0.113.5:80", None))

    db = _DomainOnlyDb([_FakeDomainRow("app.example.com")])
    entries = d.build_entries(db, object())

    assert entries == [{"domain": "app.example.com", "upstream": "203.0.113.5:80"}]


def test_build_entries_skips_dns01_for_customers_without_a_timeweb_token(monkeypatch):
    """Без токена — без DNS-01: домен просто останется недоступен по HTTPS,
    как и было, но не должен подставлять пустую строку в блок tls/dns."""
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.setattr(d, "is_private_host_ip", lambda *a, **k: True)
    monkeypatch.setattr(d, "resolve_upstream", lambda db, k8s, dom: ("10.0.0.9:80", None))

    db = _DomainOnlyDb([_FakeDomainRow("app.example.com")])
    entries = d.build_entries(db, object())

    assert entries == [{"domain": "app.example.com", "upstream": "10.0.0.9:80"}]


def test_caddyfile_empty_is_still_valid_config():
    """Пустой Caddyfile невалиден для Caddy — должна быть заглушка,
    иначе контейнер не поднимется, когда доменов ещё нет."""
    cfg = d.build_caddyfile([])
    assert cfg.strip()
    assert "respond" in cfg


# ------------------------------- DNS-проверка -------------------------------

def test_check_dns_match(monkeypatch):
    monkeypatch.setattr(d.socket, "gethostbyname", lambda h: "10.0.0.5")
    ok, detail = d.check_dns("app.example.com", "10.0.0.5")
    assert ok is True and detail == "10.0.0.5"


def test_check_dns_mismatch(monkeypatch):
    monkeypatch.setattr(d.socket, "gethostbyname", lambda h: "1.2.3.4")
    ok, detail = d.check_dns("app.example.com", "10.0.0.5")
    assert ok is False
    assert "1.2.3.4" in detail and "10.0.0.5" in detail


def test_check_dns_unresolvable(monkeypatch):
    def boom(h):
        raise OSError("NXDOMAIN")
    monkeypatch.setattr(d.socket, "gethostbyname", boom)
    ok, detail = d.check_dns("nope.example.com", "10.0.0.5")
    assert ok is False and "не резолвится" in detail


def test_check_dns_resolves_a_hostname_passed_as_expected_ip(monkeypatch):
    """Живой баг: host_for_links() отдаёт то имя, через которое сейчас
    открыта панель — если это PANEL_DOMAIN (а не IP), expected_ip приходит
    сюда доменом. Оба домена вели на один и тот же приватный IP, но
    сравнение IP-строки с доменной строкой никогда не совпадёт без резолва —
    пользователь видел «DNS ещё не готов» на верно настроенной записи."""
    def fake_gethostbyname(host):
        if host == "home.example.com":
            return "192.168.1.14"
        if host == "app.example.com":
            return "192.168.1.14"
        raise AssertionError(f"unexpected host {host}")
    monkeypatch.setattr(d.socket, "gethostbyname", fake_gethostbyname)
    ok, detail = d.check_dns("app.example.com", expected_ip="home.example.com")
    assert ok is True and detail == "192.168.1.14"


def test_check_dns_reports_hostname_it_could_not_resolve(monkeypatch):
    def fake_gethostbyname(host):
        raise OSError("NXDOMAIN")
    monkeypatch.setattr(d.socket, "gethostbyname", fake_gethostbyname)
    ok, detail = d.check_dns("app.example.com", expected_ip="broken.example.com")
    assert ok is False and "broken.example.com" in detail


def test_check_dns_still_compares_raw_ips_directly(monkeypatch):
    """Обычный путь (expected_ip уже IP) не должен трогать резолвер лишний
    раз — ipaddress.ip_address() коротко замыкает ветку резолва имени."""
    calls = []

    def fake_gethostbyname(host):
        calls.append(host)
        return "10.0.0.5"
    monkeypatch.setattr(d.socket, "gethostbyname", fake_gethostbyname)
    ok, detail = d.check_dns("app.example.com", expected_ip="10.0.0.5")
    assert ok is True
    assert calls == ["app.example.com"]  # expected_ip ни разу не резолвился


# --------------------------- Подтверждение владения --------------------------
#
# Инцидент на живом сервере: авторитетный NS Timeweb иногда отвечает 3+
# секунды, системный резолвер по умолчанию сдаётся раньше и ошибку "не успел
# ответить" не отличить от настоящего NXDOMAIN — check_ownership() возвращал
# "TXT-запись не найдена" для записи, которая на самом деле была настроена
# верно. Проверяем, что резолвер теперь явно публичный и терпеливый, а не
# системный.

class _FakeTxtAnswer:
    def __init__(self, value):
        self.strings = [value.encode()]


class _FakeDnsResolver:
    last_kwargs = None
    answers = None
    error = None

    def __init__(self, configure=True):
        type(self).last_kwargs = {"configure": configure}
        self.nameservers = None
        self.timeout = None
        self.lifetime = None

    def resolve(self, name, rdtype):
        if type(self).error:
            raise type(self).error
        return type(self).answers


def _patch_dns_resolver(monkeypatch, answers=None, error=None):
    import dns.resolver
    _FakeDnsResolver.answers = answers
    _FakeDnsResolver.error = error
    _FakeDnsResolver.last_kwargs = None
    monkeypatch.setattr(dns.resolver, "Resolver", _FakeDnsResolver)


def test_check_ownership_requires_a_token():
    ok, detail = d.check_ownership("app.example.com", "")
    assert ok is False and "нет токена" in detail


def test_check_ownership_matches_the_token(monkeypatch):
    _patch_dns_resolver(monkeypatch, answers=[_FakeTxtAnswer("aegis-verify-abc")])
    ok, detail = d.check_ownership("app.example.com", "aegis-verify-abc")
    assert ok is True and "подтверждено" in detail


def test_check_ownership_wrong_value_is_not_confused_with_missing_record(monkeypatch):
    _patch_dns_resolver(monkeypatch, answers=[_FakeTxtAnswer("something-else")])
    ok, detail = d.check_ownership("app.example.com", "aegis-verify-abc")
    assert ok is False and "нет нужного значения" in detail


def test_check_ownership_reports_resolution_failure(monkeypatch):
    _patch_dns_resolver(monkeypatch, error=Exception("boom"))
    ok, detail = d.check_ownership("app.example.com", "aegis-verify-abc")
    assert ok is False and "не найдена" in detail


def test_check_ownership_uses_public_resolvers_instead_of_the_system_default(monkeypatch):
    """Ключевая часть фикса: системный резолвер (обычно локальный стаб)
    именно этот путь и подводил — заменяем его на явные публичные адреса
    с бóльшим таймаутом, а не полагаемся на конфигурацию хоста."""
    captured = {}

    class RecordingResolver(_FakeDnsResolver):
        def __init__(self, configure=True):
            super().__init__(configure=configure)
            captured["instance"] = self

    import dns.resolver
    RecordingResolver.answers = [_FakeTxtAnswer("aegis-verify-abc")]
    RecordingResolver.error = None
    monkeypatch.setattr(dns.resolver, "Resolver", RecordingResolver)

    d.check_ownership("app.example.com", "aegis-verify-abc")

    assert RecordingResolver.last_kwargs == {"configure": False}
    assert captured["instance"].nameservers == ["1.1.1.1", "8.8.8.8"]
    assert captured["instance"].timeout >= 5
    assert captured["instance"].lifetime >= 10


# ------------------------------ Статус Caddy --------------------------------

def test_caddy_status_without_docker():
    class NoDocker:
        def is_available(self): return False
    st = d.caddy_status(NoDocker())
    assert st["docker"] is False and st["running"] is False
    assert "host_ip" in st


def test_caddyfile_tar_roundtrip():
    """Конфиг кладём в контейнер через tar — проверяем, что архив читается."""
    import tarfile
    buf = d._caddyfile_tar("hello { }")
    with tarfile.open(fileobj=buf, mode="r") as tar:
        member = tar.getmember("Caddyfile")
        assert tar.extractfile(member).read().decode() == "hello { }"


# ---------------------- публичность адреса хоста ----------------------------

@pytest.mark.parametrize("ip", [
    "192.168.31.10",   # адрес из скриншота: сервер в локальной сети
    "192.168.1.1",
    "10.0.0.5",
    "172.16.0.10",
    "172.31.255.254",
    "127.0.0.1",
    "169.254.169.254",
])
def test_private_addresses_detected(ip):
    """Let's Encrypt стучится на порт 80 ИЗВНЕ: на такой адрес сертификат
    не выпустится, и предупредить нужно до правки DNS."""
    assert d.is_private_host_ip(ip) is True


@pytest.mark.parametrize("ip", ["185.177.219.140", "8.8.8.8", "1.1.1.1"])
def test_public_addresses_pass(ip):
    assert d.is_private_host_ip(ip) is False


@pytest.mark.parametrize("ip", ["203.0.113.10", "198.51.100.7"])
def test_documentation_ranges_also_unreachable(ip):
    """Адреса из RFC 5737 (примеры в документации) не маршрутизируются —
    сертификат на них тоже не выпустится."""
    assert d.is_private_host_ip(ip) is True


def test_garbage_value_is_not_reported_as_private():
    """Имя хоста вместо адреса не должно выдавать ложное предупреждение."""
    assert d.is_private_host_ip("host.example.com") is False


def test_status_reports_whether_host_is_reachable(monkeypatch):
    monkeypatch.setenv("AEGIS_HOST_IP", "192.168.31.10")

    class NoDocker:
        def is_available(self): return False

    st = d.caddy_status(NoDocker())
    assert st["host_ip"] == "192.168.31.10"
    assert st["host_ip_is_private"] is True


# ------------------------- Вотчдог зацикленного Caddy ------------------------
#
# Реальный случай на живом сервере: Caddy застрял в бесконечном перезапуске
# (изначально — из-за конфликта порта с самой панелью), и put_archive/start/
# reload на контейнере в таком состоянии ничего не чинили — конфиг
# переписывался, а падающий процесс продолжал падать со старым состоянием.
# Восстановить панель можно было только зайдя на сервер и вручную снеся
# контейнер. Ниже — что теперь делает это само.

class FakeContainer:
    def __init__(self, status="running", restart_count=0):
        self.status = status
        self.attrs = {"RestartCount": restart_count}
        self.removed_force = None
        self.started = False
        self.put_archives = []
        self.exec_calls = []

    def reload(self):
        pass  # в тестах attrs/status уже выставлены заранее

    def remove(self, force=False):
        self.removed_force = force

    def start(self):
        self.started = True

    def put_archive(self, path, tar):
        self.put_archives.append(path)

    def exec_run(self, cmd):
        self.exec_calls.append(cmd)
        return types.SimpleNamespace(exit_code=0, output=b"")


class FakeContainersCollection:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = []

    def get(self, name):
        if self.existing is None:
            raise docker.errors.NotFound("no such container")
        return self.existing

    def create(self, image, **kwargs):
        c = FakeContainer(status="created")
        self.created.append({"image": image, "kwargs": kwargs})
        self.existing = c
        return c


class FakeImages:
    def get(self, name):
        return object()  # образ «уже есть» — не пытаемся ничего скачивать


class FakeDockerClient:
    """Подменяет HostDockerClient: .client — объект с .containers/.images,
    как у настоящего docker.DockerClient."""

    def __init__(self, existing_container=None):
        self.client = types.SimpleNamespace(
            containers=FakeContainersCollection(existing_container),
            images=FakeImages(),
        )


class FakeQuery:
    def filter(self, *a, **k):
        return self

    def all(self):
        return []


class FakeDb:
    def query(self, model):
        return FakeQuery()


def test_crash_looping_detects_restarting_status():
    c = FakeContainer(status="restarting", restart_count=0)
    assert d._caddy_crash_looping(c) is True


def test_crash_looping_detects_high_restart_count_even_if_currently_running():
    # Docker иногда успевает поднять контейнер между падениями — статус в
    # момент проверки может оказаться "running", но счётчик рестартов выдаёт
    # цикл с головой.
    c = FakeContainer(status="running", restart_count=d.CADDY_CRASH_LOOP_THRESHOLD)
    assert d._caddy_crash_looping(c) is True


def test_healthy_container_is_not_reported_as_crash_looping():
    c = FakeContainer(status="running", restart_count=0)
    assert d._caddy_crash_looping(c) is False


def test_ensure_caddy_creates_when_missing():
    fake = FakeDockerClient(existing_container=None)
    result = d.ensure_caddy(fake, "# empty")
    assert result["status"] == "created"
    assert len(fake.client.containers.created) == 1


def test_ensure_caddy_recreates_crash_looping_container_instead_of_reviving_it():
    stuck = FakeContainer(status="restarting", restart_count=7)
    fake = FakeDockerClient(existing_container=stuck)
    result = d.ensure_caddy(fake, "# new config")
    assert result["status"] == "recreated_after_crash_loop"
    assert stuck.removed_force is True
    # put_archive/start на самом зацикленном контейнере не вызывались —
    # его снесли, а не пытались починить на месте.
    assert stuck.put_archives == []
    assert len(fake.client.containers.created) == 1


def test_ensure_caddy_just_reloads_a_healthy_container():
    healthy = FakeContainer(status="running", restart_count=0)
    fake = FakeDockerClient(existing_container=healthy)
    result = d.ensure_caddy(fake, "# new config")
    assert result["status"] == "reloaded"
    assert healthy.removed_force is None
    assert any("caddy reload" in c for c in healthy.exec_calls)


def test_reconcile_caddy_does_nothing_when_container_was_never_created():
    fake = FakeDockerClient(existing_container=None)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is False
    assert fake.client.containers.created == []


def test_reconcile_caddy_bootstraps_itself_when_panel_domain_is_configured(monkeypatch):
    """Домен панели живёт в переменных окружения, а не в БД — значит, никто
    не проходит через API /domains (единственное место, которое раньше
    вызывало ensure_caddy). Первый запуск для такой установки обязан сделать
    именно вотчдог, иначе Caddy никогда не поднимется сам."""
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok-abc")
    fake = FakeDockerClient(existing_container=None)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is True
    assert len(fake.client.containers.created) == 1
    assert fake.client.containers.created[0]["image"] == d.CADDY_IMAGE


def test_reconcile_caddy_leaves_a_healthy_container_alone():
    healthy = FakeContainer(status="running", restart_count=0)
    fake = FakeDockerClient(existing_container=healthy)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is False
    assert healthy.removed_force is None


def test_reconcile_caddy_heals_a_crash_loop_without_any_domain_configured():
    """Ключевой сценарий из инцидента: доменов нет вообще, поэтому ничто в
    панели не вызвало бы ensure_caddy() само — только периодический вотчдог."""
    stuck = FakeContainer(status="restarting", restart_count=10)
    fake = FakeDockerClient(existing_container=stuck)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is True
    assert stuck.removed_force is True
    assert len(fake.client.containers.created) == 1


def test_plainly_exited_caddy_is_detected_as_stopped():
    """restart_policy=always не поднимает контейнер, остановленный явно, —
    он так и висит в exited. Пользователь на живом сервере видел ровно это:
    «а нормально, что caddy всегда выключен?». Не нормально."""
    c = FakeContainer(status="exited", restart_count=0)
    assert d._caddy_state(c) == "stopped"


def test_healthy_caddy_has_no_state_problem():
    assert d._caddy_state(FakeContainer(status="running", restart_count=0)) is None


def test_crash_loop_is_distinguished_from_a_plain_stop():
    """Лечится это по-разному: зацикленный сносим, остановленный запускаем."""
    assert d._caddy_state(FakeContainer(status="restarting", restart_count=0)) == "crash-loop"
    assert d._caddy_state(FakeContainer(status="exited", restart_count=99)) == "crash-loop"


def test_watchdog_starts_a_stopped_caddy_instead_of_recreating_it():
    stopped = FakeContainer(status="exited", restart_count=0)
    fake = FakeDockerClient(existing_container=stopped)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is True
    assert stopped.started is True
    # Пересоздавать незачем — конфиг в контейнере уже есть.
    assert stopped.removed_force is None
    assert fake.client.containers.created == []


def test_watchdog_recreates_a_stopped_caddy_that_refuses_to_start():
    class Unstartable(FakeContainer):
        def start(self):
            raise RuntimeError("port already in use")

    stuck = Unstartable(status="exited", restart_count=0)
    fake = FakeDockerClient(existing_container=stuck)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is True
    assert len(fake.client.containers.created) == 1


# ------------------- домены служебных сервисов в /status --------------------
#
# Домены панели, почты и хранилища живут в .env, а не в БД, поэтому интерфейс
# узнаёт о них только из /api/domains/status. Без этого в почте оставалась
# заглушка «user@domain.local», а S3 не мог показать ссылку на консоль.

def test_status_exposes_system_domains(monkeypatch):
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.setenv("MAIL_DOMAIN", "mail.example.com")
    monkeypatch.setenv("STORAGE_DOMAIN", "storage.example.com")

    assert d.panel_domain() == "home.example.com"
    assert d.mail_domain() == "mail.example.com"
    assert d.storage_domain() == "storage.example.com"


def test_system_domains_are_empty_strings_when_unset(monkeypatch):
    """Пустая строка, а не None: интерфейс подставляет запасной вариант через
    `mail_domain || 'aegis.local'`, и None превратился бы в текст «None»."""
    for var in ("PANEL_DOMAIN", "MAIL_DOMAIN", "STORAGE_DOMAIN"):
        monkeypatch.delenv(var, raising=False)
    assert d.panel_domain() == ""
    assert d.mail_domain() == ""
    assert d.storage_domain() == ""


# ------------- один явный УЦ вместо скитаний по staging и обратно ------------
#
# Живой инцидент, повторявшийся четыре раза подряд: Caddy держит список УЦ
# (боевой Let's Encrypt, ZeroSSL) и после нескольких неудач сам уходит на
# staging. Дальше staging и боевой выпуск идут ОДНОВРЕМЕННО по одному и тому
# же имени _acme-challenge.<домен>, каждый пишет туда свой токен и затирает
# чужой — в логе «Incorrect TXT record found». Вдобавок сертификат от staging
# браузеры не считают доверенным, а панель показывала домен активным.

def test_dns01_block_pins_the_production_ca():
    cfg = d.build_caddyfile([
        {"domain": "a.example.com", "upstream": "1.2.3.4:80", "dns_token": "tok"},
    ])
    assert f"issuer acme {d.LETSENCRYPT_PROD_CA}" in cfg
    assert "acme-v02.api.letsencrypt.org" in cfg
    # staging не должен попасть в конфиг ни при каких условиях
    assert "acme-staging" not in cfg


def test_dns_settings_live_inside_the_issuer_block():
    """dns/resolvers/propagation — параметры ACME-издателя. Оставленные на
    уровне tls, они относились бы к УЦ по умолчанию, а наш явный issuer
    остался бы без DNS-01 и провалил бы выпуск на приватном IP."""
    cfg = d.build_caddyfile([
        {"domain": "a.example.com", "upstream": "1.2.3.4:80", "dns_token": "tok"},
    ])
    issuer_at = cfg.index("issuer acme")
    closing = cfg.index("\t\t}", issuer_at)
    inside = cfg[issuer_at:closing]
    for directive in ("dns timeweb tok", "resolvers 1.1.1.1 8.8.8.8",
                      f"propagation_delay {d.ACME_PROPAGATION_DELAY}",
                      f"propagation_timeout {d.ACME_PROPAGATION_TIMEOUT}"):
        assert directive in inside, directive


def test_issuer_gets_the_contact_email_when_set():
    """Глобальный `email` относится к УЦ по умолчанию; у явного issuer свой,
    иначе ACME-аккаунт останется без контакта и уведомления об истечении
    сертификата никуда не придут."""
    cfg = d.build_caddyfile(
        [{"domain": "a.example.com", "upstream": "1.2.3.4:80", "dns_token": "tok"}],
        email="me@example.com")
    issuer_at = cfg.index("issuer acme")
    closing = cfg.index("\t\t}", issuer_at)
    assert "email me@example.com" in cfg[issuer_at:closing]


def test_plain_entries_still_have_no_issuer_block():
    """Домены на публичном IP проходят обычный HTTP-01 — им явный issuer не
    нужен, и запасной путь через ZeroSSL там скорее полезен."""
    cfg = d.build_caddyfile([{"domain": "a.example.com", "upstream": "1.2.3.4:80"}])
    assert "issuer" not in cfg


# --------- причина падения Caddy должна попадать в лог, а не в docker logs ---

class _LoggingContainer(FakeContainer):
    def __init__(self, *a, log=b"Error: loading initial config: ... address already in use", **kw):
        super().__init__(*a, **kw)
        self._log = log
        self.logs_calls = 0

    def logs(self, **kwargs):
        self.logs_calls += 1
        return self._log


def test_crash_reason_is_read_from_the_container_log():
    """Вотчдог умел пересоздать зацикленный Caddy, но писал только сам факт.
    Настоящая причина — обычно занятый порт 80/443 — оставалась внутри
    контейнера, и добраться до неё можно было лишь руками через docker logs."""
    c = _LoggingContainer(status="restarting", restart_count=5)
    reason = d._caddy_failure_reason(c)
    assert "address already in use" in reason
    assert c.logs_calls == 1


def test_crash_reason_survives_an_unreadable_log():
    """Диагностика не должна мешать восстановлению: если лог не прочитался,
    вотчдог обязан всё равно пересоздать контейнер."""
    class NoLogs(FakeContainer):
        def logs(self, **kwargs):
            raise RuntimeError("container is gone")

    c = NoLogs(status="restarting", restart_count=5)
    reason = d._caddy_failure_reason(c)
    assert "не удалось прочитать" in reason


def test_empty_log_is_reported_explicitly_not_as_blank():
    c = _LoggingContainer(status="restarting", restart_count=5, log=b"   ")
    assert "пуст" in d._caddy_failure_reason(c)


def test_watchdog_still_recreates_after_reading_the_log():
    """Главное — что диагностика не сломала само восстановление."""
    stuck = _LoggingContainer(status="restarting", restart_count=10)
    fake = FakeDockerClient(existing_container=stuck)
    assert d.reconcile_caddy(FakeDb(), object(), fake) is True
    assert stuck.removed_force is True
    assert len(fake.client.containers.created) == 1


# ------------- служебные сервисы заданы таблицей, а не ветками --------------

def test_rabbitmq_console_can_have_its_own_domain(monkeypatch):
    """Консоль RabbitMQ слушает только 127.0.0.1:15672 — без домена до неё
    можно добраться лишь SSH-туннелем."""
    for var in ("PANEL_DOMAIN", "MAIL_DOMAIN", "STORAGE_DOMAIN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("RABBITMQ_DOMAIN", "queue.example.com")
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok")

    assert d.system_domain_entries() == [
        {"domain": "queue.example.com", "upstream": d.RABBITMQ_UPSTREAM, "dns_token": "tok"},
    ]


def test_every_service_in_the_table_is_reachable_from_system_domains(monkeypatch):
    """system_domains() и system_domain_entries() читают одну и ту же таблицу —
    забыть сервис в одном из них теперь нельзя."""
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tok")
    for env, _upstream, _label in d.SYSTEM_SERVICES:
        monkeypatch.setenv(env, f"{env.lower()}.example.com")

    domains = d.system_domains()
    entries = {e["domain"] for e in d.system_domain_entries()}
    assert set(domains) == {env.lower() for env, _, _ in d.SYSTEM_SERVICES}
    assert entries == {v for v in domains.values()}


def test_service_table_has_no_duplicate_upstreams_or_vars():
    """Опечатка вида «два сервиса на одном порту» иначе всплыла бы только на
    живом сервере: Caddy проксировал бы два домена в один и тот же сервис."""
    envs = [env for env, _, _ in d.SYSTEM_SERVICES]
    ups = [u for _, u, _ in d.SYSTEM_SERVICES]
    assert len(envs) == len(set(envs))
    assert len(ups) == len(set(ups))


def test_databases_are_deliberately_absent_from_the_table():
    """Caddy — реверс-прокси для HTTP, а PostgreSQL и MariaDB общаются по
    своему бинарному протоколу поверх TCP: домен для них указывал бы в никуда.
    Явный тест, чтобы их не добавили «для полноты»."""
    ups = " ".join(u for _, u, _ in d.SYSTEM_SERVICES)
    assert ":5432" not in ups and ":3306" not in ups


# ------------- DNS-01 не только у Timeweb: провайдер выбирается токеном ------
#
# Сервер за NAT — обычное дело не только у Timeweb, а DNS-01 работает у любого
# провайдера с API. Раньше имя провайдера было зашито в генератор конфига
# строкой "dns timeweb", и добавить второго было некуда.

def test_provider_defaults_to_timeweb_for_entries_without_an_explicit_one():
    """Совместимость: записи, собранные старым кодом (только dns_token),
    должны по-прежнему давать рабочий блок Timeweb, а не пустое имя плагина."""
    cfg = d.build_caddyfile([
        {"domain": "a.example.com", "upstream": "1.2.3.4:80", "dns_token": "tok"},
    ])
    assert "dns timeweb tok" in cfg


def test_cloudflare_entry_uses_the_cloudflare_plugin():
    cfg = d.build_caddyfile([
        {"domain": "a.example.com", "upstream": "1.2.3.4:80",
         "dns_token": "cf-tok", "dns_provider": "cloudflare"},
    ])
    assert "dns cloudflare cf-tok" in cfg
    assert "dns timeweb" not in cfg


def test_dns_provider_prefers_cloudflare_when_both_tokens_are_set(monkeypatch):
    monkeypatch.setenv("TIMEWEB_DNS_API_TOKEN", "tw")
    monkeypatch.setenv("CLOUDFLARE_DNS_API_TOKEN", "cf")
    assert d.dns_provider() == ("cloudflare", "cf")


def test_dns_provider_empty_without_tokens(monkeypatch):
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_DNS_API_TOKEN", raising=False)
    assert d.dns_provider() == ("", "")


def test_system_domains_follow_the_cloudflare_token(monkeypatch):
    for var in ("MAIL_DOMAIN", "STORAGE_DOMAIN", "RABBITMQ_DOMAIN", "TIMEWEB_DNS_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    monkeypatch.setenv("CLOUDFLARE_DNS_API_TOKEN", "cf")

    assert d.panel_entry() == {
        "domain": "home.example.com",
        "upstream": d.PANEL_UPSTREAM,
        "dns_token": "cf",
        "dns_provider": "cloudflare",
    }


def test_customer_domains_follow_the_cloudflare_token_too(monkeypatch):
    monkeypatch.delenv("TIMEWEB_DNS_API_TOKEN", raising=False)
    monkeypatch.delenv("PANEL_DOMAIN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_DNS_API_TOKEN", "cf")
    monkeypatch.setattr(d, "is_private_host_ip", lambda *a, **k: True)
    monkeypatch.setattr(d, "resolve_upstream", lambda db, k8s, dom: ("10.0.0.9:80", None))

    entries = d.build_entries(_DomainOnlyDb([_FakeDomainRow("app.example.com")]), object())
    assert entries == [{
        "domain": "app.example.com", "upstream": "10.0.0.9:80",
        "dns_token": "cf", "dns_provider": "cloudflare",
    }]


def test_caddy_image_is_built_with_every_provider_we_can_select():
    """Плагин линкуется в бинарник статически: провайдер, которого нет в
    образе, даст «unknown module» и Caddy не стартует вовсе. Список провайдеров
    в коде и список плагинов в Dockerfile обязаны совпадать."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "aegis-caddy", "Dockerfile"), encoding="utf-8") as f:
        dockerfile = f.read()
    for name, _getter in d.DNS_PROVIDERS:
        assert f"caddy-dns/{name}" in dockerfile, name


# ---------- доперепроверка доменов: DNS расходится не мгновенно --------------
#
# Записи создаются в момент добавления домена (сами — см. services/dns_api.py,
# или руками у регистратора), но публичные резолверы видят их через десятки
# секунд. Проверять прямо в HTTP-обработчике бессмысленно: он почти всегда
# упрётся в «ещё не видно», и пользователю пришлось бы жать «Проверить»
# вручную до победного.

class _Row:
    def __init__(self, domain="app.example.com", status="pending"):
        self.domain = domain
        self.status = status
        self.verification_token = "aegis-verify-abc"
        self.dns_ok = False
        self.ownership_ok = False
        self.last_checked = None
        self.last_error = None


class _CommitDb:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.commits = 0
        self.closed = False

    def query(self, model):
        outer = self

        class Q:
            def filter(self, *a, **k):
                return self

            def all(self):
                return outer.rows
        return Q()

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_verify_domain_row_marks_a_good_domain_active(monkeypatch):
    monkeypatch.setattr(d, "check_ownership", lambda *a: (True, "ок"))
    monkeypatch.setattr(d, "check_dns", lambda *a, **k: (True, "10.0.0.5"))
    row, db = _Row(), _CommitDb()

    res = d.verify_domain_row(db, row, "10.0.0.5")

    assert res["ready"] is True
    assert row.status == "active" and row.dns_ok and row.ownership_ok
    assert row.last_error is None and db.commits == 1


def test_verify_domain_row_reports_the_failing_check_first(monkeypatch):
    """Пока владение не доказано, показывать «ожидает A-запись» неверно —
    пользователь пойдёт править не ту запись."""
    monkeypatch.setattr(d, "check_ownership", lambda *a: (False, "TXT не найдена"))
    monkeypatch.setattr(d, "check_dns", lambda *a, **k: (True, "10.0.0.5"))
    row, db = _Row(), _CommitDb()

    d.verify_domain_row(db, row, "10.0.0.5")

    assert row.status == "pending" and row.last_error == "TXT не найдена"


def test_autoverify_tick_does_nothing_without_pending_domains(monkeypatch):
    """Тик обязан быть дешёвым: он крутится каждую минуту на каждом сервере."""
    db = _CommitDb(rows=[])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    applied = []
    monkeypatch.setattr(d, "apply_config", lambda *a, **k: applied.append(1))

    d.autoverify_tick(object())

    assert applied == [] and db.closed is True


def test_autoverify_tick_applies_the_config_once_a_domain_becomes_ready(monkeypatch):
    monkeypatch.setattr(d, "check_ownership", lambda *a: (True, "ок"))
    monkeypatch.setattr(d, "check_dns", lambda *a, **k: (True, "10.0.0.5"))
    monkeypatch.setattr(d, "host_ip", lambda: "10.0.0.5")
    db = _CommitDb(rows=[_Row()])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    applied = []
    monkeypatch.setattr(d, "apply_config", lambda *a, **k: applied.append(1))

    d.autoverify_tick(object())

    assert applied == [1]


def test_autoverify_tick_leaves_the_config_alone_while_dns_is_not_ready(monkeypatch):
    """Перезагружать Caddy каждую минуту без причины незачем."""
    monkeypatch.setattr(d, "check_ownership", lambda *a: (False, "TXT не найдена"))
    monkeypatch.setattr(d, "check_dns", lambda *a, **k: (False, "не резолвится"))
    monkeypatch.setattr(d, "host_ip", lambda: "10.0.0.5")
    db = _CommitDb(rows=[_Row()])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    applied = []
    monkeypatch.setattr(d, "apply_config", lambda *a, **k: applied.append(1))

    d.autoverify_tick(object())

    assert applied == []


def test_one_broken_domain_does_not_stop_the_others(monkeypatch):
    """Одна упавшая проверка не должна оставлять остальные домены висеть."""
    seen = []

    def flaky(domain, token):
        seen.append(domain)
        if domain == "bad.example.com":
            raise RuntimeError("resolver exploded")
        return True, "ок"

    monkeypatch.setattr(d, "check_ownership", flaky)
    monkeypatch.setattr(d, "check_dns", lambda *a, **k: (True, "10.0.0.5"))
    monkeypatch.setattr(d, "host_ip", lambda: "10.0.0.5")
    db = _CommitDb(rows=[_Row("bad.example.com"), _Row("good.example.com")])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    monkeypatch.setattr(d, "apply_config", lambda *a, **k: None)

    d.autoverify_tick(object())

    assert seen == ["bad.example.com", "good.example.com"]


def test_worker_runs_the_autoverify_daemon():
    """Без потока в воркере домен так и остался бы «ожидающим» навсегда."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "worker.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "domains_autoverify_daemon" in src
    assert "autoverify_tick" in src


# ---------- порт домена определяется сам, а не спрашивается у человека -------
#
# Раньше форма привязки домена требовала четыре поля: домен, тип цели, саму
# цель и ОБЯЗАТЕЛЬНЫЙ внутренний порт для ВМ — то есть пользователь должен был
# помнить, что Grafana слушает 3000, а Portainer 9000. Ошибался — домен молча
# вёл в никуда, и выяснялось это через несколько минут ожидания сертификата.

class _VmRow:
    def __init__(self, template=None):
        self.cloud_init_template = template


@pytest.mark.parametrize("template,expected", [
    ("grafana", 3000),
    ("portainer", 9000),
])
def test_port_comes_from_the_template(template, expected):
    assert d.default_target_port(_VmRow(template)) == expected


@pytest.mark.parametrize("template", [None, "", "lamp", "wordpress", "docker"])
def test_plain_vm_gets_the_web_port(template):
    """У шаблонов без своего порта сервис и так на 80 — как и у чистой ВМ."""
    assert d.default_target_port(_VmRow(template)) == 80


def test_port_matches_the_forward_the_panel_creates():
    """Домен должен вести на тот же порт, на который смотрит проброс, —
    иначе сайт по домену не откроется, хотя по IP:порту работает."""
    from app.api.vms import default_ports_for

    for template in ("grafana", "portainer"):
        app = [p for p in default_ports_for(9, "ubuntu", template) if p["name"] == "APP"]
        assert app[0]["int_port"] == d.default_target_port(_VmRow(template))


def test_api_no_longer_demands_a_port_for_vms():
    """Явный отказ «Для ВМ укажите target_port» должен был исчезнуть вместе
    с полем в форме."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "domains.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    # Ищем именно отказ, а не упоминание: в комментарии рядом описано, почему
    # прежнее поведение убрали, и наивная проверка по подстроке ловила его.
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "укажите target_port" not in code
    assert "default_target_port" in code


def test_explicit_port_still_wins():
    """Ручной порт никуда не делся — он просто спрятан за ссылкой в форме."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "domains.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "req.target_port or dsvc.default_target_port(vm)" in src


def test_domain_table_does_not_print_raw_resolver_errors():
    """Под бейджем печатался сырой текст от резолвера — «TXT-запись ... не
    найдена: The DNS query name does not exist». Это не ошибка пользователя
    и не его задача: пока запись расходится, такого ответа и надо ожидать.
    Действий строка не подсказывала, наполовину была на английском и
    выглядела как поломка на месте, где всё идёт по плану. Текст остался в
    подсказке бейджа — для диагностики."""
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "frontend", "src", "components", "DomainsPanel.jsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    code = re.sub(r"\{/\*.*?\*/\}|/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
    # Ошибка не должна попадать в тело строки таблицы...
    assert ">{d.last_error}<" not in code
    # ...но должна оставаться доступной в подсказке.
    assert "d.last_error" in code and "title={hint}" in code


def test_staging_ca_is_closed_off_not_just_deprioritised():
    """Одного явного issuer оказалось мало, и это доказано логом живого
    сервера:

        challenge failed ... ca=acme-v02          (боевой, попытка 1)
        using ACME account ... acme-staging-v02   (попытки 2 и 3)

    certmagic держит ОТДЕЛЬНЫЙ тестовый CA и уходит на него после неудачи,
    чтобы не жечь лимиты боевого. На практике это вредит: staging и боевой
    выпуск идут по одному имени _acme-challenge.<домен> и затирают токены
    друг друга, а пока длится крюк — у домена нет годного сертификата, и
    браузер отвечает «не удалось установить защищённое соединение». Ровно
    это и случилось с n8n.byteburners.ru.

    Лечится тем, что тестовый каталог указывает на боевой: переключаться
    просто некуда."""
    cfg = d.build_caddyfile([
        {"domain": "a.example.com", "upstream": "1.2.3.4:80", "dns_token": "tok"},
    ])
    assert f"test_dir {d.LETSENCRYPT_PROD_CA}" in cfg
    # Ни в каком виде staging в конфиг попадать не должен.
    assert "acme-staging" not in cfg

    # test_dir — параметр издателя, а не блока tls: снаружи issuer он
    # относился бы к УЦ по умолчанию и ничего бы не закрыл.
    issuer_at = cfg.index("issuer acme")
    closing = cfg.index("\t\t}", issuer_at)
    assert "test_dir" in cfg[issuer_at:closing]


# ---------- сертификат уходит вместе с доменом ------------------------------
#
# Caddy держит сертификаты в своём томе и сам их не вычищает: домен убрали из
# конфига — сайт перестал обслуживаться, а файлы остались. На живом сервере
# так и накопились сертификаты доменов, удалённых днями раньше.

class _ExecContainer:
    def __init__(self, exit_code=0, output=b""):
        self.exit_code = exit_code
        self.output = output
        self.calls = []

    def exec_run(self, cmd):
        self.calls.append(cmd)
        return types.SimpleNamespace(exit_code=self.exit_code, output=self.output)


class _CertDocker:
    def __init__(self, container):
        self.client = types.SimpleNamespace(
            containers=types.SimpleNamespace(get=lambda name: container))


def _patch_docker(monkeypatch, container):
    import app.core.docker_client as dc
    monkeypatch.setattr(dc, "HostDockerClient", lambda: _CertDocker(container))


def test_certificate_is_removed_with_the_domain(monkeypatch):
    c = _ExecContainer()
    _patch_docker(monkeypatch, c)
    assert d.remove_certificate("app.example.com") == {"removed": True}
    # Проходим по каталогам ВСЕХ УЦ: staging от прежних версий тоже мусорит.
    assert c.calls == [["sh", "-c", "rm -rf /data/caddy/certificates/*/app.example.com"]]


def test_system_domain_certificate_is_never_removed(monkeypatch):
    """Домен панели живёт в .env, а не в БД. Но если завести такой же ещё и
    через панель, а потом удалить — снесётся сертификат самой панели, и она
    станет недоступна по HTTPS."""
    monkeypatch.setenv("PANEL_DOMAIN", "home.example.com")
    c = _ExecContainer()
    _patch_docker(monkeypatch, c)

    res = d.remove_certificate("home.example.com")
    assert res["removed"] is False and "служебн" in res["reason"]
    assert c.calls == []          # команда даже не запускалась


@pytest.mark.parametrize("bad", ["", "не домен", "a b.com", "app.example.com; rm -rf /"])
def test_garbage_never_reaches_the_shell(bad, monkeypatch):
    """Имя подставляется в команду как есть — пускать туда что попало нельзя."""
    c = _ExecContainer()
    _patch_docker(monkeypatch, c)
    assert d.remove_certificate(bad)["removed"] is False
    assert c.calls == []


def test_cleanup_failure_does_not_raise(monkeypatch):
    """Удаление домена уже произошло; уборка за собой не повод его завалить."""
    _patch_docker(monkeypatch, _ExecContainer(exit_code=1, output=b"permission denied"))
    res = d.remove_certificate("app.example.com")
    assert res["removed"] is False and "permission denied" in res["reason"]


def test_domain_deletion_cleans_up_after_applying_the_config():
    """Порядок важен: сначала конфиг без домена, потом чистка. Наоборот —
    Caddy успеет выпустить сертификат заново."""
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "api", "domains.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    block = src[src.index("def delete_domain"):]
    block = block[:block.index("db.close()")]
    assert "remove_certificate" in block
    assert block.index("_apply_config") < block.index("remove_certificate")


# ------ домен приложения маркетплейса должен находиться и на его ВМ ---------
#
# Маркетплейс создаёт СРАЗУ ДВЕ записи с одним именем: VMTask и AppDeployment
# (см. api/marketplace.py). В списке целей при добавлении домена имя поэтому
# появляется дважды — «Приложение: n8n-qte6» и «ВМ: n8n-qte6». Выбрав первое,
# пользователь получал домен с target_type == "deployment", и карточка ВМ,
# искавшая только target_type == "vm", честно писала «Домен не привязан» —
# хотя домен ведёт именно на эту ВМ.

class _Dep:
    def __init__(self, id, vm_id):
        self.id, self.vm_id = id, vm_id


class _DepDb:
    def __init__(self, deps):
        self._deps = deps

    def query(self, model):
        outer = self

        class Q:
            def filter(self, *a, **k):
                return self

            def first(self):
                return outer._deps[0] if outer._deps else None
        return Q()


def test_vm_domain_resolves_to_itself():
    from app.api.domains import _vm_id_of

    dom = types.SimpleNamespace(target_type="vm", target_id=11)
    assert _vm_id_of(_DepDb([]), dom) == 11


def test_deployment_domain_resolves_to_the_vm_it_runs_on():
    from app.api.domains import _vm_id_of

    dom = types.SimpleNamespace(target_type="deployment", target_id=7)
    assert _vm_id_of(_DepDb([_Dep(id=7, vm_id=11)]), dom) == 11


def test_deployment_without_a_vm_is_not_pinned_anywhere():
    """Деплой мог остаться без ВМ (её удалили) — тогда домен ничьей карточке
    не принадлежит, и подставлять чужую нельзя."""
    from app.api.domains import _vm_id_of

    dom = types.SimpleNamespace(target_type="deployment", target_id=7)
    assert _vm_id_of(_DepDb([]), dom) is None
    assert _vm_id_of(_DepDb([_Dep(id=7, vm_id=None)]), dom) is None


def test_vm_card_matches_domains_by_vm_id():
    """Фильтр по target_type пропускал домены приложений маркетплейса."""
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "frontend", "src", "components", "VMDetail.jsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    code = re.sub(r"//[^\n]*", "", src)
    assert "d.vm_id === vm.id" in code
    assert "d.target_type === 'vm'" not in code
