"""Checked SQL dumps and replacement restores for dedicated database pods.

PostgreSQL restores cleanup + dump in one transaction. MariaDB DDL is not
transactional, so the pod first saves its current database and recovers it if
the incoming dump fails. Never mix stderr into the SQL stored in S3.
"""
import re
import shlex
import subprocess


DB_COMMAND_TIMEOUT = 1800


def _check_target(db_name: str, engine: str):
    if not re.fullmatch(r"[a-z0-9_]{3,32}", db_name):
        raise ValueError("Некорректное имя базы данных")
    if engine not in {"postgresql", "mysql", "mariadb"}:
        raise ValueError("Неподдерживаемая СУБД")
    if engine != "postgresql" and db_name in {
        "mysql", "sys", "information_schema", "performance_schema",
    }:
        raise ValueError("Восстановление системной базы запрещено")


def validate_dump(content: str, engine: str):
    """Accept only complete plain dumps produced by the panel, including legacy ones."""
    if not isinstance(content, str) or not content.strip() or "\x00" in content:
        raise ValueError("SQL-копия пуста или повреждена; база не изменена")
    if engine == "postgresql":
        header = r"(?m)^-- PostgreSQL database dump\r?$"
        footer = r"(?m)^-- PostgreSQL database dump complete\r?$"
    else:
        header = r"(?m)^-- (?:MariaDB|MySQL) dump\b"
        footer = r"(?m)^-- Dump completed on [^\r\n]+\r?$"
    if not re.search(header, content[:2048]) or not re.search(footer, content[-2048:]):
        raise ValueError("SQL-копия не является завершённым дампом этой СУБД; база не изменена")


def _run(pod: str, namespace: str, script: str, password: str, *, sql: str = None) -> str:
    command = ["kubectl", "exec"]
    if sql is not None:
        command.append("-i")
    command += ["-n", namespace, pod, "--", "sh", "-c", script]
    try:
        result = subprocess.run(
            command, input=sql, capture_output=True, text=True,
            encoding="utf-8", timeout=DB_COMMAND_TIMEOUT,
        )
    except FileNotFoundError:
        raise RuntimeError("kubectl не найден; пересоберите контейнеры backend и worker") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "Время ожидания операции БД истекло. Не запускайте восстановление повторно: "
            "проверьте состояние операции в поде базы данных."
        ) from None
    except OSError:
        raise RuntimeError("Не удалось запустить команду в поде базы данных") from None
    if result.returncode != 0:
        detail = (result.stderr or "Команда СУБД завершилась с ошибкой").strip()
        # Neither exception argv nor a password should reach logs/API responses.
        if password:
            detail = detail.replace(password, "[скрыто]")
        raise RuntimeError(detail) from None
    return result.stdout


def _postgres_command(program: str, db_name: str, db_user: str, password: str, flags: list) -> str:
    return "PGPASSWORD=" + shlex.quote(password) + " " + shlex.join([
        program, "--no-password", "--username", db_user, "--dbname", db_name, *flags,
    ])


def _mysql_tools() -> str:
    # Credentials already exist in the dedicated MariaDB pod. Root is required
    # to dump routines/events and recreate the database without changing grants.
    return '''set -eu
export MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"
if [ -z "$MYSQL_PWD" ]; then
    echo 'В поде отсутствуют административные реквизиты MariaDB; база не изменена' >&2
    exit 1
fi
if command -v mariadb >/dev/null 2>&1; then db_client=mariadb; else db_client=mysql; fi
if command -v mariadb-dump >/dev/null 2>&1; then db_dump=mariadb-dump; else db_dump=mysqldump; fi
'''


def _operation_lock(db_name: str) -> str:
    return f'''set -eu
restore_lock=/tmp/aegis-db-restore-{db_name}.lock
if ! mkdir "$restore_lock"; then
    echo 'Для этой базы уже выполняется копирование или восстановление; база не изменена' >&2
    exit 1
fi
trap 'rmdir -- "$restore_lock"' EXIT
'''


def capture(pod: str, namespace: str, db_name: str, engine: str, db_user: str, password: str) -> str:
    _check_target(db_name, engine)
    if engine == "postgresql":
        script = _operation_lock(db_name) + _postgres_command("pg_dump", db_name, db_user, password, [
            "--clean", "--if-exists", "--no-owner", "--no-privileges",
        ])
    else:
        script = _mysql_tools() + _operation_lock(db_name) + '"$db_dump" --user=root --single-transaction --quick ' \
            '--routines --events --triggers --hex-blob --comments --dump-date -- ' + shlex.quote(db_name)
    content = _run(pod, namespace, script, password)
    validate_dump(content, engine)
    return content


def _postgres_restore_sql(content: str) -> str:
    # Dropping schemas removes objects created AFTER the backup too. pg_dump's
    # --clean alone only removes objects that also occur in the dump.
    cleanup = '''SELECT pg_catalog.pg_advisory_xact_lock(19470425);
SET LOCAL lock_timeout = '30s';
DO $aegis_cleanup$
DECLARE item record;
BEGIN
    FOR item IN SELECT extname FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'
    LOOP EXECUTE format('DROP EXTENSION IF EXISTS %I CASCADE', item.extname); END LOOP;
    FOR item IN SELECT nspname FROM pg_catalog.pg_namespace
        WHERE nspname <> 'information_schema' AND nspname !~ '^pg_'
    LOOP EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', item.nspname); END LOOP;
END $aegis_cleanup$;
SELECT pg_catalog.lo_unlink(oid) FROM pg_catalog.pg_largeobject_metadata;
'''
    # Some versions of pg_dump rely on the public schema supplied by initdb.
    # Others explicitly recreate it. Both old and new panel dumps must work.
    if not re.search(r'(?m)^CREATE SCHEMA (?:public|"public");\r?$', content):
        cleanup += 'CREATE SCHEMA public AUTHORIZATION CURRENT_USER;\n'
    return cleanup + content + "\n"


def _mysql_restore_script(db_name: str) -> str:
    quoted_db = "`" + db_name + "`"  # _check_target already rejected shell/SQL metacharacters.
    show_schema = shlex.quote("SHOW CREATE DATABASE " + quoted_db)
    drop_db = shlex.quote("DROP DATABASE IF EXISTS " + quoted_db + ";")
    return _mysql_tools() + _operation_lock(db_name) + f'''umask 077
restore_dir=''
keep_safety=0
cleanup() {{
    if [ -n "$restore_dir" ] && [ "$keep_safety" -eq 0 ]; then rm -rf -- "$restore_dir"; fi
    rmdir -- "$restore_lock"
}}
trap cleanup EXIT
restore_dir=$(mktemp -d /tmp/aegis-db-restore.XXXXXX)
cat > "$restore_dir/incoming.sql"
"$db_client" --user=root --batch --raw --skip-column-names --execute={show_schema} > "$restore_dir/schema.tsv"
cut -f2- "$restore_dir/schema.tsv" > "$restore_dir/schema.sql"
printf ';\\n' >> "$restore_dir/schema.sql"
"$db_dump" --user=root --single-transaction --quick --routines --events --triggers \\
    --hex-blob --comments --dump-date -- {shlex.quote(db_name)} > "$restore_dir/before.sql"
test -s "$restore_dir/before.sql"
grep -q '^-- Dump completed on ' "$restore_dir/before.sql"
reset_database() {{
    "$db_client" --user=root --execute={drop_db} &&
    "$db_client" --user=root < "$restore_dir/schema.sql"
}}
if reset_database && "$db_client" --user=root --database={shlex.quote(db_name)} < "$restore_dir/incoming.sql"; then
    exit 0
fi
echo 'Не удалось восстановить SQL-копию; возвращаем прежние данные' >&2
if reset_database && "$db_client" --user=root --database={shlex.quote(db_name)} < "$restore_dir/before.sql"; then
    echo 'Восстановление отменено: прежние данные возвращены' >&2
    exit 1
fi
keep_safety=1
echo "Не удалось вернуть прежние данные. Страховочная копия в поде: $restore_dir/before.sql" >&2
exit 1
'''


def restore(pod: str, namespace: str, db_name: str, engine: str, db_user: str, password: str, content: str) -> str:
    _check_target(db_name, engine)
    validate_dump(content, engine)  # No destructive command before these checks.
    if engine == "postgresql":
        script = _operation_lock(db_name) + _postgres_command("psql", db_name, db_user, password, [
            "-X", "--set", "ON_ERROR_STOP=1", "--single-transaction", "--file", "-",
        ])
        sql = _postgres_restore_sql(content)
    else:
        script = _mysql_restore_script(db_name)
        sql = content if content.endswith("\n") else content + "\n"
    _run(pod, namespace, script, password, sql=sql)
    return "Восстановление успешно завершено"
