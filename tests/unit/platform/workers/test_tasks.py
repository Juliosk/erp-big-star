"""Tests for worker retry policy and registered task behavior."""

from erp.platform.workers.celery_app import celery_app
from erp.platform.workers.tasks import RETRY_DELAYS_SECONDS


def test_worker_retry_delays_match_architecture_baseline() -> None:
    assert RETRY_DELAYS_SECONDS == (30, 120, 300, 900)


def test_outbox_task_is_registered_with_stable_name() -> None:
    celery_app.loader.import_task_module("erp.platform.workers.tasks")

    task = celery_app.tasks["erp.platform.outbox.publish_pending"]

    assert task.name == "erp.platform.outbox.publish_pending"
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
