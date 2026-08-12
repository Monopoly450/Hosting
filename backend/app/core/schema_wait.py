"""Ожидание готовности схемы БД — воркер не должен стартовать раньше неё.

Таблицы создаёт бэкенд (app/main.py, startup_event: create_all + миграции).
Воркер их не создаёт намеренно: два процесса, одновременно выполняющие
CREATE TABLE, ловят в PostgreSQL взаимную блокировку (см. закомментированный
create_all в worker.py).

Но docker compose поднимает воркер сразу после healthcheck'а самой базы —
то есть заведомо раньше, чем бэкенд успевает эти таблицы создать. Наблюдалось
на свежем сервере: каждый фоновый демон воркера немедленно падал с

    (psycopg2.errors.UndefinedTable) relation "domains" does not exist
    (psycopg2.errors.UndefinedTable) relation "vm_tasks" does not exist

и уходил в бесконечный цикл ошибок. Хуже всего доставалось вотчдогу Caddy:
он не мог собрать список доменов, а значит, не поднимал прокси — домены на
новой установке не работали вовсе, и в логах это выглядело как проблема с
DNS или сертификатами, а не как гонка при старте.

Ждать здесь дёшево и безопасно: пустая база на свежей установке заполняется
за секунды, а на уже работающем сервере таблицы есть сразу и цикл
завершается на первой же проверке.
"""
import logging
import time

logger = logging.getLogger("app.core.schema_wait")

# Таблицы, которые читают фоновые демоны воркера сразу после старта.
# Не весь список моделей: смысл проверки — поймать момент, когда бэкенд
# закончил create_all, а не сверять схему целиком.
REQUIRED_TABLES = (
    "vm_tasks",          # очередь задач и firewall/stuck-демоны
    "domains",           # вотчдог Caddy
    "clusters",          # создание ВМ в кластере
    "backup_schedules",  # планировщик бэкапов
    "alert_rules",       # движок алертов
)

# Столько ждём в худшем случае. Бэкенд на свежем сервере успевает за
# несколько секунд; пять минут — запас на медленный диск и первый прогон
# миграций, после которого продолжать ожидание бессмысленно: значит, дело
# не в гонке, а в том, что бэкенд не поднялся вовсе.
DEFAULT_TIMEOUT = 300.0
DEFAULT_INTERVAL = 2.0


def missing_tables(engine, required=REQUIRED_TABLES) -> list:
    """Каких из нужных таблиц ещё нет. Ошибка соединения = «нет ни одной»."""
    from sqlalchemy import inspect

    existing = set(inspect(engine).get_table_names())
    return [t for t in required if t not in existing]


def wait_for_schema(engine, required=REQUIRED_TABLES, timeout: float = DEFAULT_TIMEOUT,
                    interval: float = DEFAULT_INTERVAL, sleep=time.sleep,
                    monotonic=time.monotonic) -> bool:
    """Ждёт, пока бэкенд создаст таблицы. True — дождались.

    По таймауту возвращает False, но НЕ бросает исключение: демоны воркера и
    так переживают ошибки БД в своих циклах, и уронить весь воркер из-за
    медленного бэкенда было бы хуже, чем продолжить с явной записью в логе.
    """
    deadline = monotonic() + timeout
    announced = False
    while True:
        try:
            missing = missing_tables(engine, required)
        except Exception as e:
            # База ещё не принимает соединения — для нас это то же ожидание.
            missing = list(required)
            last_error = e
        else:
            last_error = None
            if not missing:
                if announced:
                    logger.info("Схема БД готова, продолжаю запуск воркера.")
                return True

        if monotonic() >= deadline:
            logger.error(
                "Схема БД не готова за %.0f с: не хватает таблиц %s%s. "
                "Проверьте бэкенд — таблицы создаёт он: docker compose logs backend",
                timeout, ", ".join(missing) or "?",
                f" (последняя ошибка: {last_error})" if last_error else "",
            )
            return False

        if not announced:
            logger.info(
                "Жду, пока бэкенд создаст таблицы (%s). Это нормально на первом запуске.",
                ", ".join(missing),
            )
            announced = True
        sleep(interval)
