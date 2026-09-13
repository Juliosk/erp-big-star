"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from erp.apps.api.import_composition import compose_imports
from erp.apps.api.middleware import CorrelationIdMiddleware, RequestIdMiddleware
from erp.apps.api.routes import health_router
from erp.apps.web.mount import mount_web
from erp.modules.admin.api import router as admin_router
from erp.modules.admin.api.session_context import router as session_router
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
from erp.modules.admin.infrastructure.dev_security import DevSecurityContextResolver
from erp.modules.customer.api import router as customer_router
from erp.modules.customer.application import (
    Customer360Service,
    CustomerDuplicateService,
    CustomerGroupService,
    CustomerQueries,
    CustomerUpdateService,
)
from erp.modules.customer.application.creation import CustomerCreationService
from erp.modules.customer.application.permissions import CustomerAuthorization
from erp.modules.customer.infrastructure.customer360 import PostgresCustomer360
from erp.modules.customer.infrastructure.customer_creation import PostgresCustomerCreation
from erp.modules.customer.infrastructure.customer_directory import PostgresCustomerDirectory
from erp.modules.customer.infrastructure.customer_duplicates import PostgresCustomerDuplicates
from erp.modules.customer.infrastructure.customer_groups import PostgresCustomerGroups
from erp.modules.customer.infrastructure.customer_updates import PostgresCustomerUpdates
from erp.modules.governance.api import router as import_router
from erp.modules.governance.application.imports import ImportService
from erp.modules.inventory.api import router as inventory_router
from erp.modules.inventory.application import (
    InventoryAdjustmentService,
    InventoryAuthorization,
    InventoryAvailabilityQueryService,
    InventoryCatalogService,
    InventoryQueries,
    InventoryReservationQueryService,
    InventoryReservationService,
)
from erp.modules.inventory.infrastructure import PostgresInventoryCatalogue
from erp.modules.inventory.infrastructure.adjustments import PostgresInventoryAdjustments
from erp.modules.inventory.infrastructure.reservations import PostgresInventoryReservations
from erp.modules.pricing.api import router as pricing_router
from erp.modules.pricing.application import (
    PricingAuthorization,
    PricingCatalogService,
    PricingResolutionService,
)
from erp.modules.pricing.infrastructure import PostgresPricingCatalogue, PostgresPricingResolver
from erp.modules.product.api import router as product_router
from erp.modules.product.application import ProductQueries
from erp.modules.product.application.barcodes import ProductBarcodeService
from erp.modules.product.application.creation import ProductCreationService
from erp.modules.product.application.lifecycle import ProductLifecycleService
from erp.modules.product.application.permissions import ProductAuthorization
from erp.modules.product.application.updates import ProductUpdateService
from erp.modules.product.infrastructure.product_barcodes import PostgresProductBarcodes
from erp.modules.product.infrastructure.product_creation import PostgresProductCreation
from erp.modules.product.infrastructure.product_directory import PostgresProductDirectory
from erp.modules.product.infrastructure.product_lifecycle import PostgresProductLifecycle
from erp.modules.product.infrastructure.product_updates import PostgresProductUpdates
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
    product_updates: ProductUpdateService | None = None,
    product_lifecycle: ProductLifecycleService | None = None,
    product_barcodes: ProductBarcodeService | None = None,
    imports: ImportService | None = None,
    customer_queries: CustomerQueries | None = None,
    customer_creation: CustomerCreationService | None = None,
    customer_updates: CustomerUpdateService | None = None,
    customer_groups: CustomerGroupService | None = None,
    customer_duplicates: CustomerDuplicateService | None = None,
    customer_360: Customer360Service | None = None,
    inventory_queries: InventoryQueries | None = None,
    inventory_creation: InventoryCatalogService | None = None,
    inventory_adjustments: InventoryAdjustmentService | None = None,
    inventory_availability: InventoryAvailabilityQueryService | None = None,
    inventory_reservation_queries: InventoryReservationQueryService | None = None,
    inventory_reservations: InventoryReservationService | None = None,
    pricing_catalogue: PricingCatalogService | None = None,
    pricing_resolution: PricingResolutionService | None = None,
) -> FastAPI:
    """Build the public HTTP application."""
    resolved_settings = settings or get_settings()
    if (
        isinstance(security_context_resolver, DevSecurityContextResolver)
        and not resolved_settings.dev_auth_enabled
    ):
        raise ValueError("Development identity requires the application flag to be enabled.")
    if resolved_settings.dev_auth_enabled:
        # Revalidate even Settings.model_copy(update=...) cannot enable this in production.
        resolved_settings = Settings.model_validate(resolved_settings.model_dump())
        if security_context_resolver is None:
            security_context_resolver = DevSecurityContextResolver(resolved_settings)
    resolved_database = database or Database(resolved_settings)
    if imports is None and isinstance(resolved_database, Database):
        imports = compose_imports(resolved_database, resolved_settings)
    resolved_company_query_service = company_query_service
    resolved_corporate_creation_service = corporate_creation_service
    resolved_corporate_hierarchy_service = corporate_hierarchy_service
    resolved_product_queries = product_queries
    resolved_customer_queries = customer_queries
    resolved_customer_creation = customer_creation
    resolved_customer_updates = customer_updates
    resolved_customer_groups = customer_groups
    resolved_customer_duplicates = customer_duplicates
    resolved_customer_360 = customer_360
    resolved_inventory_queries = inventory_queries
    resolved_inventory_creation = inventory_creation
    resolved_inventory_adjustments = inventory_adjustments
    resolved_inventory_availability = inventory_availability
    resolved_inventory_reservation_queries = inventory_reservation_queries
    resolved_inventory_reservations = inventory_reservations
    resolved_pricing_catalogue = pricing_catalogue
    resolved_pricing_resolution = pricing_resolution
    if isinstance(resolved_database, Database) and (
        resolved_inventory_queries is None
        or resolved_inventory_creation is None
        or resolved_inventory_adjustments is None
        or resolved_inventory_availability is None
        or resolved_inventory_reservation_queries is None
        or resolved_inventory_reservations is None
    ):
        inventory_catalogue = PostgresInventoryCatalogue(resolved_database)
        inventory_reservation_store = PostgresInventoryReservations(
            resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
        )
        inventory_authorization = InventoryAuthorization(
            CompanyAccessService(PostgresCorporateDirectory(resolved_database))
        )
        if resolved_inventory_queries is None:
            resolved_inventory_queries = InventoryQueries(
                inventory_catalogue, inventory_authorization
            )
        if resolved_inventory_creation is None:
            resolved_inventory_creation = InventoryCatalogService(
                inventory_catalogue, inventory_authorization
            )
        if resolved_inventory_adjustments is None:
            resolved_inventory_adjustments = InventoryAdjustmentService(
                PostgresInventoryAdjustments(
                    resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
                ),
                inventory_authorization,
            )
        if resolved_inventory_availability is None:
            resolved_inventory_availability = InventoryAvailabilityQueryService(
                inventory_reservation_store, inventory_authorization
            )
        if resolved_inventory_reservation_queries is None:
            resolved_inventory_reservation_queries = InventoryReservationQueryService(
                inventory_reservation_store, inventory_authorization
            )
        if resolved_inventory_reservations is None:
            resolved_inventory_reservations = InventoryReservationService(
                inventory_reservation_store, inventory_authorization
            )
    if resolved_pricing_catalogue is None and isinstance(resolved_database, Database):
        resolved_pricing_catalogue = PricingCatalogService(
            PostgresPricingCatalogue(
                resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
            ),
            PricingAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_pricing_resolution is None and isinstance(resolved_database, Database):
        resolved_pricing_resolution = PricingResolutionService(
            PostgresPricingResolver(resolved_database),
            PricingAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_customer_360 is None and isinstance(resolved_database, Database):
        resolved_customer_360 = Customer360Service(
            PostgresCustomer360(resolved_database),
            CustomerAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_customer_duplicates is None and isinstance(resolved_database, Database):
        resolved_customer_duplicates = CustomerDuplicateService(
            PostgresCustomerDuplicates(resolved_database),
            CustomerAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_customer_groups is None and isinstance(resolved_database, Database):
        resolved_customer_groups = CustomerGroupService(
            PostgresCustomerGroups(resolved_database),
            CustomerAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_customer_updates is None and isinstance(resolved_database, Database):
        resolved_customer_updates = CustomerUpdateService(
            PostgresCustomerUpdates(resolved_database),
            CustomerAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_customer_creation is None and isinstance(resolved_database, Database):
        resolved_customer_creation = CustomerCreationService(
            PostgresCustomerCreation(
                resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
            ),
            CustomerAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if resolved_customer_queries is None and isinstance(resolved_database, Database):
        resolved_customer_queries = CustomerQueries(
            PostgresCustomerDirectory(resolved_database),
            CustomerAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if product_barcodes is None and isinstance(resolved_database, Database):
        product_barcodes = ProductBarcodeService(
            PostgresProductBarcodes(
                resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
            ),
            ProductAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    if product_lifecycle is None and isinstance(resolved_database, Database):
        product_lifecycle = ProductLifecycleService(
            PostgresProductLifecycle(
                resolved_database, ttl_seconds=resolved_settings.idempotency_ttl_seconds
            ),
            ProductAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
    resolved_product_updates = product_updates
    if resolved_product_updates is None and isinstance(resolved_database, Database):
        resolved_product_updates = ProductUpdateService(
            PostgresProductUpdates(resolved_database),
            ProductAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(resolved_database))
            ),
        )
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
    application.state.product_updates = resolved_product_updates
    application.state.product_lifecycle = product_lifecycle
    application.state.product_barcodes = product_barcodes
    application.state.imports = imports
    application.state.customer_queries = resolved_customer_queries
    application.state.customer_creation = resolved_customer_creation
    application.state.customer_updates = resolved_customer_updates
    application.state.customer_groups = resolved_customer_groups
    application.state.customer_duplicates = resolved_customer_duplicates
    application.state.customer_360 = resolved_customer_360
    application.state.inventory_queries = resolved_inventory_queries
    application.state.inventory_creation = resolved_inventory_creation
    application.state.inventory_adjustments = resolved_inventory_adjustments
    application.state.inventory_availability = resolved_inventory_availability
    application.state.inventory_reservation_queries = resolved_inventory_reservation_queries
    application.state.inventory_reservations = resolved_inventory_reservations
    application.state.pricing_catalogue = resolved_pricing_catalogue
    application.state.pricing_resolution = resolved_pricing_resolution
    register_error_handlers(application)
    application.include_router(health_router)
    application.include_router(admin_router)
    application.include_router(product_router)
    application.include_router(customer_router)
    application.include_router(inventory_router)
    application.include_router(pricing_router)
    application.include_router(session_router)
    application.include_router(import_router)
    mount_web(application)
    # Starlette wraps the last-added middleware first: Request ID must be outermost.
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(RequestIdMiddleware)
    return application


app = create_app()

__all__ = ["app", "create_app"]
