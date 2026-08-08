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
    """Инцидент на живом сервере: без задержки Let's Encrypt иногда спрашивал
    TXT-запись раньше, чем она реально разошлась у Timeweb (каждая ACME-
    попытка запрашивает новый токен), а проверка НАПРЯМУЮ через авторитетные
    NS домена подвисала на прямом TCP:53 наружу и падала по таймауту. При
    нескольких одновременных доменах NS Timeweb не укладывался и в дефолтный
    двухминутный propagation_timeout — увеличен с запасом."""
    cfg = d.build_caddyfile([
        {"domain": "home.example.com", "upstream": "127.0.0.1:8081", "dns_token": "tok-123"},
    ])
    assert "propagation_delay 30s" in cfg
    assert "propagation_timeout 5m" in cfg
    assert "resolvers 1.1.1.1 8.8.8.8" in cfg


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
