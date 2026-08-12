"""Воркер не должен стартовать раньше, чем бэкенд создаст таблицы.

Живой инцидент на новой установке: docker compose поднимает воркер сразу за
healthcheck'ом PostgreSQL, то есть раньше бэкенда, который эти таблицы и
создаёт. Все шесть фоновых демонов воркера немедленно падали с

    (psycopg2.errors.UndefinedTable) relation "domains" does not exist
    (psycopg2.errors.UndefinedTable) relation "vm_tasks" does not exist

и уходили в цикл ошибок; вотчдог Caddy при этом не мог собрать список доменов
и не поднимал прокси — на свежем сервере домены не работали вовсе.
"""
import os
import sys

import pytest

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("AEGIS_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aegis")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import schema_wait as sw


class FakeClock:
    """Время под контролем теста — иначе проверка таймаута шла бы минутами."""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def monotonic(self):
        return self.t

    def sleep(self, sec):
        self.slept.append(sec)
        self.t += sec


def fake_engine(*snapshots):
    """Инспектор, отдающий по очереди заданные наборы таблиц.

    Последний набор повторяется — как настоящая база, которая, однажды
    получив таблицы, их не теряет.
    """
    state = {"i": 0}

    class Inspector:
        def get_table_names(self):
            i = min(state["i"], len(snapshots) - 1)
            state["i"] += 1
            snap = snapshots[i]
            if isinstance(snap, Exception):
                raise snap
            return list(snap)

    return Inspector()


@pytest.fixture(autouse=True)
def patch_inspect(monkeypatch):
    """sqlalchemy.inspect(engine) в тестах отдаёт наш объект как есть."""
    import sqlalchemy
    monkeypatch.setattr(sqlalchemy, "inspect", lambda engine: engine)


ALL = list(sw.REQUIRED_TABLES)


# ------------------------------ missing_tables -------------------------------

def test_no_missing_tables_when_schema_is_complete():
    assert sw.missing_tables(fake_engine(ALL)) == []


def test_missing_tables_lists_exactly_what_is_absent():
    assert sw.missing_tables(fake_engine(["vm_tasks"])) == [
        t for t in sw.REQUIRED_TABLES if t != "vm_tasks"
    ]


def test_extra_tables_do_not_bother_us():
    """Схема живёт своей жизнью — лишние таблицы это норма, а не проблема."""
    assert sw.missing_tables(fake_engine(ALL + ["users", "audit_logs"])) == []


def test_domains_and_vm_tasks_are_both_required():
    """Именно этих двух не хватало в логах инцидента."""
    assert "domains" in sw.REQUIRED_TABLES
    assert "vm_tasks" in sw.REQUIRED_TABLES


# ------------------------------ wait_for_schema ------------------------------

def test_returns_immediately_when_tables_already_exist():
    clock = FakeClock()
    assert sw.wait_for_schema(fake_engine(ALL), sleep=clock.sleep, monotonic=clock.monotonic) is True
    assert clock.slept == []          # уже работающий сервер не ждёт ни секунды


def test_waits_until_the_backend_creates_the_tables():
    clock = FakeClock()
    engine = fake_engine([], ["vm_tasks"], ALL)
    assert sw.wait_for_schema(engine, sleep=clock.sleep, monotonic=clock.monotonic) is True
    assert len(clock.slept) == 2      # два круга ожидания, потом схема готова


def test_a_database_that_refuses_connections_counts_as_waiting():
    """Пока PostgreSQL не принимает соединения, ошибка инспектора — это то же
    ожидание, а не повод сдаться."""
    clock = FakeClock()
    engine = fake_engine(RuntimeError("connection refused"), ALL)
    assert sw.wait_for_schema(engine, sleep=clock.sleep, monotonic=clock.monotonic) is True


def test_gives_up_after_the_timeout_but_does_not_raise():
    """По таймауту воркер должен продолжить работу с явной записью в логе:
    уронить его целиком из-за медленного бэкенда было бы хуже."""
    clock = FakeClock()
    ok = sw.wait_for_schema(fake_engine([]), timeout=10, interval=2,
                            sleep=clock.sleep, monotonic=clock.monotonic)
    assert ok is False
    assert sum(clock.slept) <= 10 + 2   # не крутится дольше отведённого


def test_timeout_message_names_the_missing_tables(caplog):
    clock = FakeClock()
    with caplog.at_level("ERROR"):
        sw.wait_for_schema(fake_engine([]), timeout=1, interval=1,
                           sleep=clock.sleep, monotonic=clock.monotonic)
    assert "domains" in caplog.text
    assert "docker compose logs backend" in caplog.text


# -------------------------- подключение в воркере ----------------------------

def test_worker_waits_before_starting_its_daemons():
    """Порядок в main() и есть весь смысл: если демоны стартуют раньше
    ожидания, каждый из них снова начнёт с падения на пустой базе."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "worker.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    main_at = src.index("def main():")
    wait_at = src.index("wait_for_schema(engine)", main_at)
    first_thread = src.index("threading.Thread(", main_at)
    assert wait_at < first_thread
