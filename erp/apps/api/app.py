"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from erp.apps.api.middleware import CorrelationIdMiddleware, RequestIdMiddleware
from erp.apps.api.routes import health_router
from erp.modules.admin.api import router as admin_router
from erp.modules.admin.application import (
    CorporateCreationService,
    CorporateHierarchyService,
    ListCompaniesService,
    SecurityContextResolver,
)
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.infrastructure import (
    PostgresCorporateCommandStore,
    PostgresCorporateDirectory,
)
from erp.modules.product.api import router as product_router
from erp.modules.product.application import ProductQueries
from erp.modules.product.application.creation import ProductCreationService
from erp.modules.product.application.permissions import ProductAuthorization
from erp.modules.product.infrastructure.product_creation import PostgresProductCreation
from erp.modules.product.infrastructure.product_directory import PostgresProductDirectory
from erp.platform.config import Settings, get_settings
from erp.platform.database import Database, ManagedDatabase
from erp.platform.errors import register_error_handlers
from erp.platform.observability import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: ManagedDatabase | None = None,
    *,
    company_query_service: ListCompaniesService | None = None,
    corporate_creation_service: CorporateCreationService | None = None,
    corporate_hierarchy_service: CorporateHierarchyService | None = None,
    security_context_resolver: SecurityContextResolver | None = None,
    product_queries: ProductQueries | None = None,
    product_creation: ProductCreationService | None = None,
) -> FastAPI:
    """Build the public HTTP application."""
    resolved_settings = settings or get_settings()
    resolved_database = database or Database(resolved_settings)
    resolved_company_query_service = company_query_service
    resolved_corporate_creation_service = corporate_creation_service
    resolved_corporate_hierarchy_service = corporate_hierarchy_service
    resolved_product_queries = product_queries
    resolved_product_creation = product_creation
    if resolved_product_creation is None and isinstance(resolved_database, Database):
        resolved_product_creation = ProductCreationService(
            PostgresProductCreation(
                resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
            ),
            ProductAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_product_queries is None and isinstance(resolved_database, Database):
        resolved_product_queries = ProductQueries(
            PostgresProductDirectory(resolved_database),
            ProductAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_company_query_service is None and isinstance(resolved_database, Database):
        resolved_company_query_service = ListCompaniesService(
            PostgresCorporateDirectory(resolved_database)
        )
    if resolved_corporate_creation_service is None and isinstance(resolved_database, Database):
        resolved_corporate_creation_service = CorporateCreationService(
            PostgresCorporateCommandStore(
                resolved_database,
                idempotency_ttl_seconds=resolved_settings.idempotency_ttl_seconds,
            )
        )
    if resolved_corporate_hierarchy_service is None and isinstance(resolved_database, Database):
        resolved_corporate_hierarchy_service = CorporateHierarchyService(
            PostgresCorporateDirectory(resolved_database)
        )
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
    application.state.company_query_service = resolved_company_query_service
    application.state.corporate_creation_service = resolved_corporate_creation_service
    application.state.corporate_hierarchy_service = resolved_corporate_hierarchy_service
    application.state.security_context_resolver = security_context_resolver
    application.state.product_queries = resolved_product_queries
    application.state.product_creation = resolved_product_creation
    register_error_handlers(application)
    application.include_router(health_router)
    application.include_router(admin_router)
    application.include_router(product_router)
    # Starlette wraps the last-added middleware first: Request ID must be outermost.
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(RequestIdMiddleware)
    return application


app = create_app()

__all__ = ["app", "create_app"]
