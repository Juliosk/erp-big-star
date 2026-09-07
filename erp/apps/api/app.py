"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from erp.apps.api.middleware import CorrelationIdMiddleware, RequestIdMiddleware
from erp.apps.api.routes import health_router
from erp.modules.platform_test.api import router as platform_test_router
from erp.modules.platform_test.application import CreateTestEntityService
from erp.modules.platform_test.infrastructure import (
    PostgresTestEntityPersistence,
    RabbitTestEntityTransport,
)
from erp.platform.config import Settings, get_settings
from erp.platform.database import Database, ManagedDatabase
from erp.platform.errors import register_error_handlers
from erp.platform.messaging import RabbitMQBroker
from erp.platform.observability import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: ManagedDatabase | None = None,
    test_entity_service: CreateTestEntityService | None = None,
) -> FastAPI:
    """Build the public HTTP application."""
    resolved_settings = settings or get_settings()
    resolved_database = database or Database(resolved_settings)
    broker = RabbitMQBroker(resolved_settings)
    resolved_test_entity_service = test_entity_service
    if resolved_test_entity_service is None and isinstance(resolved_database, Database):
        resolved_test_entity_service = CreateTestEntityService(
            persistence=PostgresTestEntityPersistence(
                resolved_database,
                idempotency_ttl_seconds=resolved_settings.idempotency_ttl_seconds,
            ),
            transport=RabbitTestEntityTransport(resolved_database, broker),
        )
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("application.started")
        try:
            yield
        finally:
            await broker.close()
            await resolved_database.dispose()
            logger.info("application.stopped")

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database = resolved_database
    application.state.test_entity_service = resolved_test_entity_service
    register_error_handlers(application)
    application.include_router(health_router)
    application.include_router(platform_test_router)
    # Starlette wraps the last-added middleware first: Request ID must be outermost.
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(RequestIdMiddleware)
    return application


app = create_app()

__all__ = ["app", "create_app"]
