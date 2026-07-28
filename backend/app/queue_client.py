import logging
import os
import json
import pika

logger = logging.getLogger("app.queue_client")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def publish_task_or_fail_task(queue_name: str, task_data: dict, db, task):
    """Ставит задачу в очередь; если очередь недоступна — сразу помечает запись
    как Error.

    Запись ВМ к этому моменту уже закоммичена, и rollback её не уберёт. Без
    этого она осталась бы в Pending навсегда, занимая квоту пользователя, пока
    её не подберёт демон разбора зависших задач (а это до получаса).
    """
    try:
        publish_task(queue_name, task_data)
        return True
    except Exception as e:
        logger.error(f"Не удалось поставить задачу в очередь: {e}")
        try:
            task.status = "Error"
            task.error_message = ("Сервис очередей недоступен, задача не поставлена. "
                                  "Удалите запись и попробуйте ещё раз.")
            db.commit()
        except Exception as inner:
            logger.error(f"Не удалось пометить задачу как Error: {inner}")
        return False


def publish_task(queue_name: str, task_data: dict):
    parameters = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    
    channel.queue_declare(queue=queue_name, durable=True)
    
    channel.basic_publish(
        exchange='',
        routing_key=queue_name,
        body=json.dumps(task_data),
        properties=pika.BasicProperties(
            delivery_mode=2,  # make message persistent
        )
    )
    
    connection.close()
