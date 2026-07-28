"""Разбор задач, зависших в статусе Pending.

Между «запись в БД создана» и «воркер её обработал» есть несколько мест, где
цепочка может оборваться, и тогда ВМ остаётся в Pending навсегда:

* очередь недоступна в момент publish_task — строка уже закоммичена, откатить
  её rollback не может, и сообщение никто не отправит;
* воркер перезапустился между подтверждением сообщения и обработкой —
  подтверждение уже отправлено, задача потеряна;
* воркер был выключен, пока сообщение лежало в очереди, и очередь очистили.

Такая запись не просто висит в интерфейсе — она занимает квоту пользователя.
Демон переводит её в Error с понятной причиной, но только если ВМ действительно
нет в кластере: задача могла просто долго создаваться.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("app.services.stuck_tasks")

# Сколько ждём, прежде чем считать задачу зависшей. Импорт большого образа
# идёт долго, поэтому берём с запасом.
STUCK_AFTER_MINUTES = 30

STUCK_MESSAGE = (
    "Задача не была обработана: сервис создания ВМ был недоступен. "
    "Удалите запись и попробуйте создать машину заново."
)


def find_stuck_tasks(db, now: datetime = None, minutes: int = STUCK_AFTER_MINUTES) -> list:
    """Задачи, которые слишком долго висят в Pending."""
    from app.models.models import VMTask

    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=minutes)
    return (db.query(VMTask)
              .filter(VMTask.status == "Pending", VMTask.created_at < cutoff)
              .all())


def vm_exists_in_cluster(k8s, name: str):
    """True/False — есть ли ВМ в кластере; None, если проверить не удалось.

    Разделять важно: при недоступном Kubernetes нельзя объявлять задачу
    провалившейся, иначе мы пометим Error вполне живые машины.
    """
    try:
        return bool(k8s.get_vm(name))
    except Exception as e:
        text = str(e).lower()
        if "not found" in text or "404" in text:
            return False
        logger.warning(f"Не удалось проверить ВМ {name}: {e}")
        return None


def reap_stuck_tasks(k8s, now: datetime = None) -> int:
    """Один проход: помечает зависшие задачи как Error. Возвращает их число."""
    from app.db import SessionLocal

    db = SessionLocal()
    reaped = 0
    try:
        for task in find_stuck_tasks(db, now):
            exists = vm_exists_in_cluster(k8s, task.name)
            if exists is None:
                continue          # кластер недоступен — решим на следующем проходе
            if exists:
                # ВМ на самом деле создалась, а статус не обновили
                task.status = "Running"
                logger.info(f"Задача {task.name}: ВМ найдена в кластере, статус исправлен")
            else:
                task.status = "Error"
                task.error_message = STUCK_MESSAGE
                reaped += 1
                logger.warning(f"Задача {task.name} висела в Pending — помечена как Error")
        db.commit()
    except Exception as e:
        logger.error(f"Ошибка разбора зависших задач: {e}")
        db.rollback()
    finally:
        db.close()
    return reaped
