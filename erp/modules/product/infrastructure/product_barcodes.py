"""Tenant-bound barcode persistence with aggregate CAS and atomic effects."""

from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from erp.modules.product.application.barcodes import AddBarcode, BarcodeResult, BarcodeView
from erp.modules.product.domain.barcode import BarcodeType
from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.product.infrastructure.product_effects import ProductEffects
from erp.modules.product.infrastructure.product_repository import ProductRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresProductBarcodes:
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def list(self, company_id: UUID, product_id: UUID) -> tuple[BarcodeView, ...]:
        async with self._database.session() as session:
            if await ProductRepository(session, company_id=company_id).get(product_id) is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Product not found.", status_code=404
                )
            rows = await session.scalars(
                select(ProductBarcodeModel)
                .where(
                    ProductBarcodeModel.company_id == company_id,
                    ProductBarcodeModel.product_id == product_id,
                )
                .order_by(ProductBarcodeModel.barcode)
            )
            return tuple(
                BarcodeView(
                    row.id,
                    row.company_id,
                    row.product_id,
                    BarcodeType(row.barcode_type),
                    row.barcode,
                )
                for row in rows
            )

    async def add(self, command: AddBarcode, actor_id: UUID) -> BarcodeResult:
        try:
            async with self._database.session() as session, session.begin():
                decision = await self._idempotency.begin(
                    session,
                    scope=f"product:{command.company_id}:{actor_id}",
                    operation="product.barcode.add",
                    key=command.idempotency_key,
                    payload=command.payload(),
                )
                if decision.replayed:
                    if decision.response_body is None:
                        raise RuntimeError("Stored barcode replay has no response body.")
                    return BarcodeResult.replay(decision.response_body)
                repository = ProductRepository(session, company_id=command.company_id)
                before = await repository.get(command.product_id)
                if before is None:
                    raise ApplicationError(
                        code="RESOURCE_NOT_FOUND", message="Product not found.", status_code=404
                    )
                if before.version != command.expected_version:
                    raise OptimisticLockError(expected_version=command.expected_version)
                saved = await repository.save(
                    replace(before, version=before.version + 1), actor_id=actor_id
                )
                barcode = BarcodeView(
                    uuid4(),
                    command.company_id,
                    command.product_id,
                    command.barcode_type,
                    command.barcode,
                )
                session.add(
                    ProductBarcodeModel(
                        id=barcode.id,
                        company_id=barcode.company_id,
                        product_id=barcode.product_id,
                        barcode_type=barcode.barcode_type,
                        barcode=barcode.barcode,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
                await session.flush()
                effects = await ProductEffects().record(
                    session,
                    saved,
                    actor_id=actor_id,
                    metadata=command.metadata,
                    event_type="ProductBarcodeChanged",
                    before=before,
                    audit_details={
                        "added_barcode": {
                            "id": str(barcode.id),
                            "barcode_type": barcode.barcode_type,
                            "barcode": barcode.barcode,
                        }
                    },
                    payload={
                        "product_id": str(saved.id),
                        "barcode_type": barcode.barcode_type,
                        "barcode": barcode.barcode,
                    },
                )
                result = BarcodeResult(effects, barcode)
                await self._idempotency.complete(
                    session, decision, response_status=201, response_body=result.to_dict()
                )
                return result
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="BARCODE_CONFLICT",
                    message="Barcode is already used in this company.",
                    status_code=409,
                ) from error
            raise


__all__ = ["PostgresProductBarcodes"]
