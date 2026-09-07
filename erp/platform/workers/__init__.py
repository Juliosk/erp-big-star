"""Celery worker application and reliable platform tasks."""

from erp.platform.workers.celery_app import celery_app, create_celery

__all__ = ["celery_app", "create_celery"]
