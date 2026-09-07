"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from erp.apps.api.routes import health_router
from erp.platform.config import Settings, get_settings
from erp.platform.database import Database, ManagedDatabase
from erp.platform.observability import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: ManagedDatabase | None = None,
) -> FastAPI:
    """Build the public HTTP application."""
    resolved_settings = settings or get_settings()
    resolved_database = database or Database(resolved_settings)
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("application.started")
        try:
            yield
        finally:
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
    application.include_router(health_router)
    return application


app = create_app()

__all__ = ["app", "create_app"]
