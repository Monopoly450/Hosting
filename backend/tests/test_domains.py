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
