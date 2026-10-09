"""Opt-in real SQL restore tests. Only temporary, unpublished LOCAL containers.

HOSTING_DB_ARCHIVE_INTEGRATION=1 backend/venv/bin/python -m pytest -q \
    backend/tests/test_database_archives_integration.py
"""
import os
import subprocess
import time
import uuid
from types import SimpleNamespace as NS

import pytest

from app.services import db_archives as archives


pytestmark = pytest.mark.skipif(
    os.environ.get("HOSTING_DB_ARCHIVE_INTEGRATION") != "1",
    reason="Real database tests require opt-in and a local Docker daemon",
)


@pytest.fixture(scope="module", params=["postgresql", "mysql"])
def database_pod(request):
    context = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not context.startswith("unix://"):
        pytest.fail("Refusing to connect to a non-local Docker endpoint")
    base = ["docker", "--host", context]
    engine = request.param
    name = "hosting-db-archive-test-" + uuid.uuid4().hex[:12]
    password = "archive_test_only_password"
    env = (["POSTGRES_USER=archive_user", "POSTGRES_DB=archive_test", "POSTGRES_PASSWORD=" + password]
           if engine == "postgresql" else ["MARIADB_USER=archive_user", "MARIADB_DATABASE=archive_test",
                                          "MARIADB_PASSWORD=" + password, "MARIADB_ROOT_PASSWORD=" + password])
    image = "postgres:15-alpine" if engine == "postgresql" else "mariadb:10.11-jammy"
    command = base + ["run", "--detach", "--name", name, "--label", "hosting-db-archive-test=true"]
    for item in env:
        command += ["-e", item]
    command += [image]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
    pod = NS(name=name, base=base, engine=engine, password=password)
    try:
        for _ in range(90):
            ready = subprocess.run(base + ["exec", name, "sh", "-c", (
                "PGPASSWORD=" + password + " psql -h 127.0.0.1 -U archive_user -d archive_test -Atc 'SELECT 1'"
                if engine == "postgresql" else "MYSQL_PWD=" + password + " mariadb -h 127.0.0.1 -u root --database=archive_test -NBe 'SELECT 1'"
            )], capture_output=True, text=True, timeout=5)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("Temporary database did not become ready")
        yield pod
    finally:
        # Remove only our exact UUID-named and labelled test container.
        label = subprocess.run(base + ["inspect", "--format", '{{index .Config.Labels "hosting-db-archive-test"}}', name],
                               capture_output=True, text=True, check=True).stdout.strip()
        if label == "true":
            subprocess.run(base + ["rm", "--force", name], capture_output=True, check=True)


@pytest.fixture
def real_db(database_pod, monkeypatch):
    pod = database_pod
    original_run = subprocess.run

    def local_exec(command, **kwargs):
        if command[:2] == ["kubectl", "exec"]:
            suffix = command[command.index("--") + 1:]
            command = pod.base + ["exec"] + (["-i"] if "-i" in command else []) + [pod.name] + suffix
        return original_run(command, **kwargs)

    monkeypatch.setattr(archives.subprocess, "run", local_exec)

    def sql(content):
        script = ("PGPASSWORD=" + pod.password + " psql -X -v ON_ERROR_STOP=1 -U archive_user -d archive_test -At"
                  if pod.engine == "postgresql" else "MYSQL_PWD=" + pod.password + " mariadb -u root --database=archive_test -NB")
        return archives._run(pod.name, "default", script, pod.password, sql=content)

    def dump(legacy=False):
        if not legacy:
            return archives.capture(pod.name, "default", "archive_test", pod.engine, "archive_user", pod.password)
        script = ("PGPASSWORD=" + pod.password + " pg_dump -U archive_user -d archive_test"
                  if pod.engine == "postgresql" else "MYSQL_PWD=" + pod.password + " mariadb-dump -u root archive_test")
        return archives._run(pod.name, "default", script, pod.password)

    def restore(content):
        return archives.restore(pod.name, "default", "archive_test", pod.engine, "archive_user", pod.password, content)

    # Each test starts with an empty, complete database snapshot, exercising
    # empty snapshots rather than implementing a separate destructive reset.
    if pod.engine == "postgresql":
        empty = "-- PostgreSQL database dump\nCREATE SCHEMA public;\n-- PostgreSQL database dump complete\n"
    else:
        empty = "-- MariaDB dump 10.19\n-- Dump completed on 2026-10-09\n"
    restore(empty)
    return NS(engine=pod.engine, sql=sql, dump=dump, restore=restore)


@pytest.mark.parametrize("legacy", [False, True])
def test_real_restore_replaces_records_and_removes_new_objects(real_db, legacy):
    db = real_db
    db.sql("CREATE TABLE items (id int PRIMARY KEY, value varchar(100)); "
           "INSERT INTO items VALUES (1, 'До отката'), (2, 'saved'); "
           "CREATE TABLE children (id int PRIMARY KEY, parent_id int REFERENCES items(id)); "
           "INSERT INTO children VALUES (1, 1); "
           "CREATE VIEW saved_view AS SELECT value FROM items;")
    if db.engine == "mysql" and not legacy:
        db.sql("CREATE PROCEDURE saved_proc() SELECT COUNT(*) FROM items; "
               "CREATE EVENT saved_event ON SCHEDULE EVERY 1 DAY DISABLE DO SELECT 1;")
    content = db.dump(legacy)
    db.sql("UPDATE items SET value='changed' WHERE id=1; DELETE FROM items WHERE id=2; "
           "INSERT INTO items VALUES (3, 'new'); CREATE TABLE extra_table (id int); "
           "CREATE VIEW extra_view AS SELECT * FROM extra_table;")
    if db.engine == "postgresql":
        db.sql("CREATE SCHEMA extra_schema; CREATE TABLE extra_schema.extra (id int);")
    else:
        db.sql("CREATE PROCEDURE extra_proc() SELECT 1;")
    assert db.restore(content) == "Восстановление успешно завершено"
    rows = db.sql("SELECT id, value FROM items ORDER BY id;")
    assert "До отката" in rows and "saved" in rows
    assert "changed" not in rows and "new" not in rows
    assert db.sql("SELECT COUNT(*) FROM children;").strip() == "1"
    assert "До отката" in db.sql("SELECT value FROM saved_view;")
    assert db.sql("SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('extra_table', 'extra_view');").strip() == "0"
    if db.engine == "postgresql":
        assert db.sql("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='extra_schema';").strip() == "0"
    else:
        assert db.sql("SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema='archive_test' AND routine_name='extra_proc';").strip() == "0"
        if not legacy:
            assert db.sql("CALL saved_proc();").strip() == "2"
            assert db.sql("SELECT COUNT(*) FROM information_schema.events WHERE event_schema='archive_test' AND event_name='saved_event';").strip() == "1"


def test_real_sql_failure_keeps_or_recovers_pre_restore_database(real_db):
    db = real_db
    db.sql("CREATE TABLE items (id int PRIMARY KEY, value varchar(100)); INSERT INTO items VALUES (1, 'snapshot');")
    content = db.dump()
    db.sql("UPDATE items SET value='keep current'; CREATE TABLE after_backup (id int); INSERT INTO after_backup VALUES (7);")
    marker = "-- PostgreSQL database dump complete" if db.engine == "postgresql" else "-- Dump completed on"
    broken = content.replace(marker, "SELECT * FROM missing_restore_table;\n" + marker)
    with pytest.raises(RuntimeError):
        db.restore(broken)
    assert db.sql("SELECT value FROM items;").strip() == "keep current"
    assert db.sql("SELECT id FROM after_backup;").strip() == "7"
    # A failed restore must also release its operation lock.
    assert marker in db.dump()


def test_postgres_restore_includes_sequences_schemas_and_large_objects(real_db):
    db = real_db
    if db.engine != "postgresql":
        pytest.skip("PostgreSQL-specific objects")
    db.sql('CREATE SCHEMA "Схема"; CREATE TABLE "Схема".items (id serial PRIMARY KEY, value text); '
           'INSERT INTO "Схема".items (value) VALUES (\'saved\'); '
           "SELECT lo_from_bytea(7001, decode('abcdef', 'hex'));")
    content = db.dump()
    db.sql('INSERT INTO "Схема".items (value) VALUES (\'new\'); '
           "SELECT lo_put(7001, 0, decode('000000', 'hex')); "
           "SELECT lo_from_bytea(7002, decode('11', 'hex'));")
    db.restore(content)
    assert db.sql('SELECT COUNT(*) FROM "Схема".items;').strip() == "1"
    assert db.sql('INSERT INTO "Схема".items (value) VALUES (\'next\') RETURNING id;').splitlines()[0] == "2"
    assert db.sql("SELECT encode(lo_get(7001), 'hex');").strip() == "abcdef"
    assert db.sql("SELECT COUNT(*) FROM pg_largeobject_metadata WHERE oid=7002;").strip() == "0"
