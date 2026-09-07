"""Celery application configured for durable RabbitMQ execution."""

from urllib.parse import quote

from celery import Celery, signals
from kombu import Exchange, Queue

from erp.platform.config import Settings, get_settings
from erp.platform.observability import configure_logging


def rabbitmq_broker_url(settings: Settings) -> str:
    """Build a percent-encoded AMQP URL without logging its credentials."""
    username = quote(settings.rabbitmq_default_user, safe="")
    password = quote(settings.rabbitmq_default_pass.get_secret_value(), safe="")
    virtual_host = settings.rabbitmq_virtual_host
    path = "//" if virtual_host == "/" else f"/{quote(virtual_host.lstrip('/'), safe='')}"
    return (
        f"amqp://{username}:{password}@{settings.rabbitmq_host}:{settings.rabbitmq_amqp_port}{path}"
    )


def create_celery(settings: Settings | None = None) -> Celery:
    """Build the worker app with explicit serialization, ACK and routing policy."""
    resolved = settings or get_settings()
    requests_exchange = Exchange(
        resolved.rabbitmq_requests_exchange,
        type="topic",
        durable=True,
    )
    application = Celery(
        "erp",
        broker=rabbitmq_broker_url(resolved),
        include=["erp.platform.workers.tasks"],
    )
    application.conf.update(
        accept_content=["json"],
        broker_connection_retry_on_startup=True,
        broker_transport_options={"confirm_publish": True},
        enable_utc=True,
        result_serializer="json",
        task_acks_late=True,
        task_default_exchange=resolved.rabbitmq_requests_exchange,
        task_default_exchange_type="topic",
        task_default_queue="erp.default",
        task_default_routing_key="tasks.default",
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 4,
            "interval_start": 0,
            "interval_step": 0.5,
            "interval_max": 2,
        },
        task_queues=(
            Queue("erp.default", requests_exchange, routing_key="tasks.default", durable=True),
            Queue(
                "erp.maintenance",
                requests_exchange,
                routing_key="tasks.maintenance.#",
                durable=True,
            ),
        ),
        task_reject_on_worker_lost=True,
        task_routes={
            "erp.platform.outbox.publish_pending": {
                "queue": "erp.maintenance",
                "routing_key": "tasks.maintenance.outbox-publisher",
            }
        },
        task_serializer="json",
        timezone="UTC",
        worker_hijack_root_logger=False,
        worker_prefetch_multiplier=1,
    )
    return application


def configure_worker_logging(**_: object) -> None:
    """Reuse the API JSON formatter for worker process diagnostics."""
    configure_logging(get_settings())


signals.setup_logging.connect(configure_worker_logging, weak=False)
celery_app = create_celery()

__all__ = ["celery_app", "create_celery", "rabbitmq_broker_url"]
