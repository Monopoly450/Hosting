import os
import json
import pika

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

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
