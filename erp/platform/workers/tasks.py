"""Reliable Celery task entry points for platform maintenance work."""

import asyncio
import logging
from typing import Any, NoReturn, cast

from celery import Task

from erp.platform.config import Settings, get_settings
from erp.platform.database import Database
from erp.platform.messaging import RabbitMQBroker
from erp.platform.outbox import OutboxPublisher, PublishBatchResult
from erp.platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (30, 120, 300, 900)


class OutboxPublicationError(RuntimeError):
    """Retryable failure reported when one or more publications failed."""


class ReliableTask(Task):  # type: ignore[misc]
    """Task base with the approved four-step retry policy."""

    abstract = True

    def retry_transient(self, error: Exception) -> NoReturn:
        """Reschedule after 30 s, 2 min, 5 min and 15 min, then fail."""
        retries = int(self.request.retries)
        if retries >= len(RETRY_DELAYS_SECONDS):
            raise error
        raise self.retry(
            exc=error,
            countdown=RETRY_DELAYS_SECONDS[retries],
            max_retries=len(RETRY_DELAYS_SECONDS),
        )


async def publish_outbox_batch(settings: Settings, *, batch_size: int) -> PublishBatchResult:
    """Execute one Outbox pass with isolated database and AMQP lifecycles."""
    database = Database(settings)
    broker = RabbitMQBroker(settings)
    try:
        async with database.session() as session, session.begin():
            return await OutboxPublisher(broker).publish_batch(session, limit=batch_size)
    finally:
        await broker.close()
        await database.dispose()


def publish_pending_outbox(self: ReliableTask, batch_size: int = 100) -> dict[str, int]:
    """Publish pending Outbox events; retry the task when any publication fails."""
    result = asyncio.run(publish_outbox_batch(get_settings(), batch_size=batch_size))
    if result.failed:
        logger.warning(
            "outbox.publish_batch.retry",
            extra={"published": result.published, "failed": result.failed},
        )
        self.retry_transient(
            OutboxPublicationError(f"{result.failed} Outbox publication(s) failed.")
        )
    return {"published": result.published, "failed": result.failed}


publish_pending_outbox_task = cast(
    Any,
    celery_app.task(
        bind=True,
        base=ReliableTask,
        name="erp.platform.outbox.publish_pending",
        queue="erp.maintenance",
        acks_late=True,
        reject_on_worker_lost=True,
    )(publish_pending_outbox),
)

__all__ = [
    "RETRY_DELAYS_SECONDS",
    "OutboxPublicationError",
    "ReliableTask",
    "publish_outbox_batch",
    "publish_pending_outbox_task",
]
