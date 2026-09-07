"""Tests for Celery routing, serialization and credential handling."""

from erp.platform.config import Settings
from erp.platform.workers.celery_app import create_celery, rabbitmq_broker_url


def settings() -> Settings:
    return Settings.model_validate(
        {
            "environment": "test",
            "rabbitmq_default_user": "user@example.com",
            "rabbitmq_default_pass": "p@ss:/word",
            "rabbitmq_host": "rabbit.internal",
            "rabbitmq_amqp_port": 5673,
        }
    )


def test_broker_url_percent_encodes_credentials() -> None:
    url = rabbitmq_broker_url(settings())

    assert url == "amqp://user%40example.com:p%40ss%3A%2Fword@rabbit.internal:5673//"
    assert "p@ss:/word" not in url


def test_celery_uses_durable_json_late_ack_policy_and_domain_queues() -> None:
    application = create_celery(settings())

    assert application.conf.task_serializer == "json"
    assert application.conf.accept_content == ["json"]
    assert application.conf.task_acks_late is True
    assert application.conf.task_reject_on_worker_lost is True
    assert application.conf.worker_prefetch_multiplier == 1
    assert {queue.name for queue in application.conf.task_queues} == {
        "erp.default",
        "erp.maintenance",
    }
    route = application.conf.task_routes["erp.platform.outbox.publish_pending"]
    assert route["queue"] == "erp.maintenance"
