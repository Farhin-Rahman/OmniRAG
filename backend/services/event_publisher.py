import pika
import logging
from config.settings import settings
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def publish_event(topic: str, data: BaseModel):
    """
    Publishes an event to a RabbitMQ topic exchange.

    This function connects to RabbitMQ, declares a topic exchange, and publishes
    a Pydantic model as a JSON message to the specified topic.

    Args:
        topic (str): The topic to publish the event to.
        data (BaseModel): The Pydantic model to publish as the event data.
    """
    try:
        connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
        channel = connection.channel()

        channel.exchange_declare(exchange="omnirag_exchange", exchange_type="topic")

        message = data.model_dump_json()

        channel.basic_publish(
            exchange="omnirag_exchange",
            routing_key=topic,
            body=message,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,  # make message persistent
            ),
        )

        logger.info(f"Published event to topic '{topic}': {message}")
        connection.close()
    except Exception as e:
        logger.error(f"Failed to publish event to topic '{topic}': {e}")
