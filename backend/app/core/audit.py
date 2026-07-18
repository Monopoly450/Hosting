import re
import logging

logger = logging.getLogger("app.core.audit")


def resolve_username(request) -> str:
    """Определяет, кто выполняет запрос: по Bearer-токену или X-Admin-Token."""
    try:
        from app.core.auth import decode_access_token, ADMIN_TOKEN
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            payload = decode_access_token(auth.split(" ", 1)[1])
            if payload and payload.get("sub"):
                return payload["sub"]
        xtok = request.headers.get("x-admin-token") or request.headers.get("X-Admin-Token")
        if xtok and xtok == ADMIN_TOKEN:
            return "admin"
    except Exception:
        pass
    return "anonymous"


# Человекочитаемые действия по (метод, шаблон пути)
_RULES = [
    ("POST",   r"^/api/auth/login$",                 "Вход в систему"),
    ("POST",   r"^/api/auth/register$",              "Создание пользователя"),
    ("DELETE", r"^/api/auth/users/\d+$",             "Удаление пользователя"),
    ("PUT",    r"^/api/auth/users/\d+$",             "Изменение пользователя/квот"),
    ("POST",   r"^/api/auth/change-password$",       "Смена своего пароля"),
    ("POST",   r"^/api/vms$",                         "Создание ВМ"),
    ("POST",   r"^/api/vms/([^/]+)/clone$",          "Клонирование ВМ «{0}»"),
    ("DELETE", r"^/api/vms/([^/]+)$",                "Удаление ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/start$",          "Запуск ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/stop$",           "Остановка ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/restart$",        "Перезагрузка ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/settings$",       "Изменение настроек/файрвола ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/resize$",         "Изменение ресурсов ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/migrate$",        "Миграция ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/execute$",        "Выполнение команды в ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/backup$",         "Создание бэкапа ВМ «{0}»"),
    ("DELETE", r"^/api/vms/([^/]+)/backups/",        "Удаление бэкапа ВМ «{0}»"),
    ("POST",   r"^/api/vms/([^/]+)/restore/",        "Восстановление ВМ «{0}» из бэкапа"),
    ("POST",   r"^/api/vms/balancer/pools$",         "Создание балансировщика"),
    ("DELETE", r"^/api/vms/balancer/pools/",         "Удаление балансировщика"),
    ("POST",   r"^/api/clusters$",                    "Создание кластера"),
    ("DELETE", r"^/api/clusters/\d+$",               "Удаление кластера"),
    ("POST",   r"^/api/clusters/\d+/attach$",        "Добавление ВМ в кластер"),
    ("POST",   r"^/api/databases$",                   "Создание базы данных"),
    ("DELETE", r"^/api/databases/\d+$",              "Удаление базы данных"),
    ("POST",   r"^/api/databases/\d+/bind$",         "Привязка/отвязка БД"),
    ("POST",   r"^/api/s3$",                          "Создание S3-бакета"),
    ("DELETE", r"^/api/s3/\d+$",                     "Удаление S3-бакета"),
    ("POST",   r"^/api/s3/\d+/upload$",             "Загрузка файла в S3"),
    ("POST",   r"^/api/volumes$",                     "Создание сетевого диска"),
    ("DELETE", r"^/api/volumes/\d+$",               "Удаление сетевого диска"),
    ("POST",   r"^/api/deployments$",                "Создание деплоя приложения"),
    ("DELETE", r"^/api/deployments/\d+$",           "Удаление деплоя"),
    ("POST",   r"^/api/deployments/\d+/redeploy$",   "Передеплой приложения"),
    ("POST",   r"^/api/external-servers$",           "Подключение внешнего сервера"),
    ("DELETE", r"^/api/external-servers/",          "Отключение внешнего сервера"),
    ("POST",   r"^/api/external-servers/[^/]+/execute$", "Команда на внешнем сервере"),
    ("POST",   r"^/api/images/upload$",             "Загрузка образа диска"),
    ("DELETE", r"^/api/images/",                    "Удаление образа диска"),
    ("POST",   r"^/api/snapshots",                   "Создание снапшота"),
    ("POST",   r"^/api/tokens$",                     "Создание API-токена"),
    ("DELETE", r"^/api/tokens/\d+$",                 "Отзыв API-токена"),
    ("POST",   r"^/api/backup-schedules$",           "Создание расписания бэкапов"),
    ("PUT",    r"^/api/backup-schedules/\d+$",       "Изменение расписания бэкапов"),
    ("DELETE", r"^/api/backup-schedules/\d+$",       "Удаление расписания бэкапов"),
    ("POST",   r"^/api/backup-schedules/\d+/run$",   "Ручной запуск бэкапа по расписанию"),
]


def action_for(method: str, path: str) -> str:
    for m, pat, label in _RULES:
        if m == method:
            match = re.match(pat, path)
            if match:
                try:
                    return label.format(*match.groups())
                except Exception:
                    return label
    return f"{method} {path}"


def build_audit_entry_data(request, status_code: int) -> dict:
    """Собирает данные события аудита из запроса (синхронно, пока request жив)."""
    path = request.url.path
    return {
        "username": resolve_username(request),
        "ip": request.client.host if request.client else "unknown",
        "method": request.method,
        "path": path,
        "action": action_for(request.method, path),
        "status_code": status_code,
        "success": status_code < 400,
    }


# Ретеншн журнала: хранить не дольше стольких дней
AUDIT_RETENTION_DAYS = 90
_prune_counter = [0]


def prune_old_audit(db):
    """Периодически (раз в ~300 записей) чистит журнал от записей старше ретеншна,
    чтобы таблица audit_logs не росла бесконечно."""
    import datetime
    _prune_counter[0] += 1
    if _prune_counter[0] % 300 != 0:
        return
    try:
        from app.models.models import AuditLog
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=AUDIT_RETENTION_DAYS)
        db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        logger.warning(f"audit prune failed: {e}")


def log_request_audit(request, status_code: int):
    """Синхронно записывает событие аудита. Best-effort (для прямого вызова)."""
    try:
        from app.db import SessionLocal
        from app.models.models import AuditLog
        db = SessionLocal()
        try:
            db.add(AuditLog(**build_audit_entry_data(request, status_code)))
            db.commit()
            prune_old_audit(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"audit log failed: {e}")
