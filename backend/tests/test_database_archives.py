from types import SimpleNamespace as NS
from unittest.mock import MagicMock
import subprocess

import pytest
from fastapi import HTTPException

from app.services import db_archives as archives
from app.core.k8s_client import K8sClient
from app.api import databases


PG_DUMP = "--\n-- PostgreSQL database dump\n--\nCREATE TABLE public.items (id int);\n-- PostgreSQL database dump complete\n--\n"
MY_DUMP = "-- MariaDB dump 10.19\nCREATE TABLE items (id int);\n-- Dump completed on 2026-10-09 12:00:00\n"


@pytest.fixture
def runner(monkeypatch):
    run = MagicMock(return_value=NS(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(archives.subprocess, "run", run)
    return run


@pytest.mark.parametrize("engine,dump", [("postgresql", PG_DUMP), ("mysql", MY_DUMP), ("mariadb", MY_DUMP)])
def test_complete_legacy_dumps_are_accepted(engine, dump):
    archives.validate_dump(dump, engine)


@pytest.mark.parametrize("engine,content", [
    ("postgresql", ""), ("mysql", "  "), ("postgresql", "SELECT 1;"),
    ("postgresql", PG_DUMP.split("-- PostgreSQL database dump complete")[0]),
    ("mysql", MY_DUMP.split("-- Dump completed on")[0]),
    ("postgresql", MY_DUMP), ("mysql", PG_DUMP), ("mysql", MY_DUMP + "\x00"),
])
def test_invalid_copy_is_rejected_before_any_pod_command(runner, engine, content):
    with pytest.raises(ValueError, match="база не изменена"):
        archives.restore("db-pod", "default", "demo", engine, "user", "secret", content)
    runner.assert_not_called()


def test_postgres_restore_cleans_all_schemas_and_large_objects_atomically(runner):
    assert archives.restore("db-pod", "private", "demo", "postgresql", "user", "secret", PG_DUMP) == "Восстановление успешно завершено"
    command = runner.call_args.args[0]
    assert command[:7] == ["kubectl", "exec", "-i", "-n", "private", "db-pod", "--"]
    script = command[-1]
    assert "ON_ERROR_STOP=1" in script
    assert "--single-transaction --file -" in script
    assert " -X " in script
    sql = runner.call_args.kwargs["input"]
    assert "DROP SCHEMA IF EXISTS %I CASCADE" in sql
    assert "nspname !~ '^pg_'" in sql
    assert "nspname <> 'information_schema'" in sql
    assert "DROP EXTENSION IF EXISTS %I CASCADE" in sql
    assert "pg_catalog.lo_unlink(oid)" in sql
    assert sql.index("DROP SCHEMA") < sql.index("CREATE TABLE")
    assert "CREATE SCHEMA public AUTHORIZATION CURRENT_USER;" in sql
    assert "pg_advisory_xact_lock" in sql


def test_explicit_public_schema_in_dump_is_not_created_twice(runner):
    dump = PG_DUMP.replace("CREATE TABLE", "CREATE SCHEMA public;\nCREATE TABLE")
    archives.restore("pod", "default", "demo", "postgresql", "user", "secret", dump)
    assert "CREATE SCHEMA public AUTHORIZATION" not in runner.call_args.kwargs["input"]


def test_pg_dump_preserves_stderr_separately_and_handles_words_error_in_data(runner):
    content = PG_DUMP.replace("CREATE TABLE", "-- application error message\nCREATE TABLE")
    runner.return_value = NS(returncode=0, stdout=content, stderr="NOTICE: a harmless warning\n")
    assert archives.capture("pod", "default", "demo", "postgresql", "user", "secret") == content
    script = runner.call_args.args[0][-1]
    assert "--clean --if-exists --no-owner --no-privileges" in script
    assert "--no-password" in script
    assert runner.call_args.kwargs["input"] is None


@pytest.mark.parametrize("operation", ["capture", "restore"])
@pytest.mark.parametrize("engine", ["postgresql", "mysql"])
def test_nonzero_exit_never_reports_success(runner, operation, engine):
    runner.return_value = NS(returncode=3, stdout="CREATE TABLE\n", stderr="ERROR: duplicate key\n")
    args = ["pod", "default", "demo", engine, "user", "secret"]
    if operation == "restore":
        args += [PG_DUMP if engine == "postgresql" else MY_DUMP]
    with pytest.raises(RuntimeError, match="duplicate key"):
        getattr(archives, operation)(*args)


def test_incomplete_backup_is_not_returned_for_upload(runner):
    runner.return_value.stdout = "-- PostgreSQL database dump\nCREATE TABLE demo (id int);"
    with pytest.raises(ValueError, match="завершённым дампом"):
        archives.capture("pod", "default", "demo", "postgresql", "user", "secret")


def test_mysql_uses_pod_root_without_exposing_root_password_and_dumps_routines(runner):
    runner.return_value.stdout = MY_DUMP
    archives.capture("pod", "default", "demo", "mysql", "user", "client-secret")
    script = runner.call_args.args[0][-1]
    assert "MARIADB_ROOT_PASSWORD" in script
    assert "--routines --events --triggers" in script
    assert "--single-transaction" in script
    assert "client-secret" not in script
    assert 'trap' in script and 'exec "$db_dump"' not in script


def test_mysql_restore_backs_up_before_reset_and_has_failure_recovery(runner):
    archives.restore("pod", "default", "demo", "mysql", "user", "secret", MY_DUMP)
    script = runner.call_args.args[0][-1]
    assert "SHOW CREATE DATABASE `demo`" in script
    assert "DROP DATABASE IF EXISTS `demo`" in script
    assert script.index('> "$restore_dir/before.sql"') < script.index("if reset_database")
    assert 'grep -q' in script
    assert 'reset_database && "$db_client" --user=root --database=demo < "$restore_dir/before.sql"' in script
    assert "keep_safety=1" in script
    assert "mktemp -d" in script and "umask 077" in script
    assert 'mkdir "$restore_lock"' in script
    assert runner.call_args.kwargs["input"] == MY_DUMP


@pytest.mark.parametrize("engine,db_name", [
    ("mysql", "mysql"), ("mysql", "sys"), ("mysql", "information_schema"),
    ("mysql", "performance_schema"), ("postgresql", "demo; drop database postgres"),
    ("oracle", "demo"), ("postgresql", "русский"),
])
def test_invalid_target_does_not_run_commands(runner, engine, db_name):
    with pytest.raises(ValueError):
        archives.restore("pod", "default", db_name, engine, "user", "secret", PG_DUMP)
    runner.assert_not_called()


def test_password_is_shell_quoted_and_not_in_exception(runner):
    password = "test'$(echo unsafe)"
    runner.return_value = NS(returncode=1, stdout="", stderr=f"connection rejected: {password}")
    with pytest.raises(RuntimeError) as error:
        archives.restore("pod", "default", "demo", "postgresql", "user", password, PG_DUMP)
    assert password not in str(error.value)
    import shlex
    script = runner.call_args.args[0][-1].splitlines()[-1]
    assert shlex.split(script)[0] == "PGPASSWORD=" + password


@pytest.mark.parametrize("error,match", [
    (FileNotFoundError("missing"), "kubectl не найден"),
    (subprocess.TimeoutExpired(["secret"], 1800), "Не запускайте восстановление повторно"),
    (PermissionError("secret"), "Не удалось запустить"),
])
def test_launch_failures_are_explicit_and_do_not_leak_command(runner, error, match):
    runner.side_effect = error
    with pytest.raises(RuntimeError, match=match) as caught:
        archives.restore("pod", "default", "demo", "postgresql", "user", "secret", PG_DUMP)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("method,service", [("execute_db_backup", "capture"), ("execute_db_restore", "restore")])
def test_k8s_client_delegates_to_checked_archive_service(monkeypatch, method, service):
    k8s = K8sClient.__new__(K8sClient)
    k8s.api_client = None
    core = MagicMock()
    core.list_namespaced_pod.return_value.items = [NS(metadata=NS(name="db-pod"))]
    monkeypatch.setattr("app.core.k8s_client.client.CoreV1Api", lambda *a: core)
    run = MagicMock(return_value="done")
    monkeypatch.setattr(archives, service, run)
    args = ["demo", "postgresql", "user", "secret"]
    if service == "restore":
        args.append(PG_DUMP)
    assert getattr(k8s, method)(*args, namespace="private") == "done"
    run.assert_called_once_with("db-pod", "private", *args)


@pytest.fixture
def api_env(monkeypatch):
    row = NS(id=8, owner_id=1, project_id=None, db_name="demo", db_type="postgresql", db_user="user", db_password="encrypted")
    session = MagicMock()
    session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = row
    monkeypatch.setattr(databases, "SessionLocal", lambda: session)
    monkeypatch.setattr(databases, "require_access", lambda *a, **kw: None)
    monkeypatch.setattr(databases, "decrypt_secret", lambda value: "secret")
    s3 = MagicMock()
    response = MagicMock()
    response.read.return_value = PG_DUMP.encode()
    s3.get_object.return_value = response
    monkeypatch.setattr("app.api.s3.get_minio_client", lambda: s3)
    monkeypatch.setattr("app.services.backup_storage.find_database_object", lambda *a: ("bucket", "key"))
    k8s = MagicMock()
    k8s.execute_db_restore.return_value = "Восстановление успешно завершено"
    monkeypatch.setattr("app.core.k8s_client.K8sClient", lambda: k8s)
    return session, k8s, s3, response


def test_api_restore_only_reports_success_after_checked_restore(api_env):
    session, k8s, _, response = api_env
    result = databases.restore_database_backup(8, "backup.sql", NS(id=1))
    assert result["status"] == "Success"
    k8s.execute_db_restore.assert_called_once_with(db_name="demo", engine="postgresql", db_user="user", db_password="secret", sql_content=PG_DUMP)
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
    session.close.assert_called_once()


def test_api_restore_errors_never_become_http_success(api_env):
    _, k8s, _, _ = api_env
    k8s.execute_db_restore.side_effect = RuntimeError("ERROR: invalid SQL")
    with pytest.raises(HTTPException) as error:
        databases.restore_database_backup(8, "backup.sql", NS(id=1))
    assert error.value.status_code == 500
    assert "invalid SQL" in error.value.detail


def test_s3_decode_failure_closes_stream_and_does_not_touch_database(api_env):
    _, k8s, _, response = api_env
    response.read.return_value = b"\xff"
    with pytest.raises(HTTPException):
        databases.restore_database_backup(8, "backup.sql", NS(id=1))
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
    k8s.execute_db_restore.assert_not_called()


def test_dump_failure_never_uploads_a_successful_backup(api_env):
    _, k8s, s3, _ = api_env
    k8s.execute_db_backup.side_effect = RuntimeError("pg_dump failed")
    with pytest.raises(HTTPException) as error:
        databases.create_database_backup(8, NS(id=1))
    assert error.value.status_code == 500
    s3.put_object.assert_not_called()
