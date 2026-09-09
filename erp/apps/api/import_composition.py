"""The composition root alone wires the M23/M2 shared transaction."""

from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.governance.application.imports import ImportService
from erp.modules.governance.infrastructure.import_store import PostgresImportStore
from erp.modules.product.application.permissions import ProductAuthorization
from erp.modules.product.infrastructure.product_imports import PostgresProductImports
from erp.platform.config import Settings
from erp.platform.database import Database
from erp.platform.storage import ObjectStorage
from erp.platform.storage.minio import MinioStorage


def compose_imports(
    database: Database,
    settings: Settings,
    storage: ObjectStorage | None = None,
) -> ImportService:
    companies = CompanyAccessService(PostgresCorporateDirectory(database))
    authorization = ProductAuthorization(companies)
    if storage is None and settings.import_storage_access_key:
        storage = MinioStorage(settings)
    store = PostgresImportStore(
        database,
        storage,
        lambda session, company, context, metadata: PostgresProductImports(
            session, company, context, authorization, metadata
        ),
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    return ImportService(store, companies)


__all__ = ["compose_imports"]
