"""Ограничение частоты создающих операций.

Квоты ограничивают итоговый объём ресурсов, но не темп запросов: цикл
«создать — удалить» проходит по квоте бесконечно и при этом нагружает
Kubernetes, очередь и диск. Здесь — скользящее окно на пользователя и действие.

Счётчик хранится в памяти процесса: при нескольких воркерах uvicorn лимит
действует на каждый из них отдельно. Для учебной инсталляции этого достаточно;
при переезде на несколько процессов состояние нужно вынести в Redis.
"""
import logging
import threading
import time
from collections import defaultdict

from fastapi import HTTPException, status

logger = logging.getLogger("app.core.ratelimit")

# (действие, id пользователя) -> список моментов запросов
_events = defaultdict(list)
_lock = threading.Lock()

# Сколько операций за окно разрешено. Значения подобраны так, чтобы обычная
# работа через интерфейс их не задевала: человек не создаёт 10 ВМ за минуту.
DEFAULT_LIMITS = {
    "create_vm": (10, 60),
    "create_cluster": (3, 60),
    "create_database": (10, 60),
    "create_deployment": (10, 60),
    "marketplace_deploy": (5, 60),
    "create_backup": (20, 60),
}


def _prune(key, now: float, window: int):
    fresh = [t for t in _events[key] if now - t < window]
    if fresh:
        _events[key] = fresh
    else:
        _events.pop(key, None)
    return fresh


def check_rate_limit(user, action: str, limit: int = None, window: int = None):
    """Регистрирует попытку и бросает 429, если частота превышена.

    Админа не ограничиваем: массовые операции — часть его работы.
    """
    if getattr(user, "role", None) == "admin":
        return

    default_limit, default_window = DEFAULT_LIMITS.get(action, (20, 60))
    limit = limit or default_limit
    window = window or default_window

    key = (action, getattr(user, "id", None))
    now = time.time()

    with _lock:
        # Заодно подчищаем чужие протухшие записи, чтобы словарь не рос вечно
        if len(_events) > 1000:
            for k in list(_events.keys()):
                _prune(k, now, window)

        fresh = _prune(key, now, window)
        if len(fresh) >= limit:
            retry_after = int(window - (now - min(fresh))) + 1
            logger.warning(f"Rate limit: пользователь {key[1]}, действие {action}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Слишком много операций «{action}». "
                       f"Разрешено {limit} за {window} с. Повторите через {retry_after} с.",
                headers={"Retry-After": str(retry_after)},
            )
        _events[key].append(now)


def reset_rate_limits():
    """Сброс счётчиков (используется в тестах)."""
    with _lock:
        _events.clear()
