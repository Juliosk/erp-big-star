"""Tenant-bound repositories for channel configuration, SKU mapping and orders."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.domain.channels import (
    ChannelOrderItem,
    ChannelOrderReference,
    ChannelOrderSnapshot,
    ChannelOrderStatus,
    ChannelSkuMapping,
    ChannelSkuMappingEntry,
    Marketplace,
    MultichannelSalesOrder,
    SalesChannelAccount,
    SalesChannelConflictError,
    SalesChannelScopeError,
    SalesChannelVersionConflictError,
)
from erp.modules.sales.infrastructure.channel_model import (
    ChannelSalesOrderModel,
    ExternalOrderMappingModel,
    SalesChannelConfigModel,
)


@dataclass(frozen=True, slots=True)
class ChannelOrderIngestion:
    order: MultichannelSalesOrder
    replayed: bool


def _account(model: SalesChannelConfigModel) -> SalesChannelAccount:
    return SalesChannelAccount(
        id=model.id,
        company_id=model.company_id,
        account_id=model.account_id,
        marketplace=Marketplace(model.marketplace),
        display_name=model.display_name,
        credential_reference=model.credential_reference,
        active=model.active,
        record_version=model.version,
    )


def _mapping(model: ExternalOrderMappingModel) -> ChannelSkuMappingEntry:
    return ChannelSkuMappingEntry(
        id=model.id,
        channel_config_id=model.channel_config_id,
        mapping=ChannelSkuMapping(
            company_id=model.company_id,
            account_id=model.account_id,
            marketplace=Marketplace(model.marketplace),
            listing_id=model.listing_id,
            variation_id=model.variation_id,
            external_sku=model.external_sku,
            product_id=model.product_id,
        ),
        active=model.active,
        record_version=model.version,
    )


def _serialized_items(snapshot: ChannelOrderSnapshot) -> list[dict[str, str]]:
    return [
        {
            "external_item_id": item.external_item_id,
            "listing_id": item.mapping.listing_id,
            "variation_id": item.mapping.variation_id,
            "external_sku": item.mapping.external_sku,
            "product_id": str(item.mapping.product_id),
            "quantity": str(item.quantity),
            "unit_price": str(item.unit_price),
            "discount_amount": str(item.discount_amount),
        }
        for item in snapshot.items
    ]


def _order(model: ChannelSalesOrderModel) -> MultichannelSalesOrder:
    reference = ChannelOrderReference(
        company_id=model.company_id,
        account_id=model.account_id,
        marketplace=Marketplace(model.marketplace),
        external_order_id=model.external_order_id,
    )
    items = tuple(
        ChannelOrderItem(
            external_item_id=value["external_item_id"],
            mapping=ChannelSkuMapping(
                company_id=model.company_id,
                account_id=model.account_id,
                marketplace=Marketplace(model.marketplace),
                listing_id=value["listing_id"],
                variation_id=value["variation_id"],
                external_sku=value["external_sku"],
                product_id=UUID(value["product_id"]),
            ),
            quantity=Decimal(value["quantity"]),
            unit_price=Decimal(value["unit_price"]),
            discount_amount=Decimal(value["discount_amount"]),
        )
        for value in model.items
    )
    return MultichannelSalesOrder(
        id=model.id,
        channel_config_id=model.channel_config_id,
        snapshot=ChannelOrderSnapshot(
            reference=reference,
            status=ChannelOrderStatus(model.status),
            items=items,
            freight_amount=model.freight_amount,
            discount_amount=model.discount_amount,
            currency=model.currency,
        ),
        source_fingerprint=model.source_payload_hash,
        record_version=model.version,
    )


class _TenantRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    @staticmethod
    def _actor(actor_id: UUID) -> None:
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("actor_id must be a non-zero UUID.")

    async def _flush_conflict(self, message: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise SalesChannelConflictError(message) from error
            raise


class SalesChannelConfigRepository(_TenantRepository):
    async def add(
        self, account: SalesChannelAccount, *, actor_id: UUID
    ) -> SalesChannelAccount:
        self._validate(account, actor_id)
        if account.record_version != 1:
            raise ValueError("A new channel configuration must start at version one.")
        self._session.add(
            SalesChannelConfigModel(
                id=account.id,
                company_id=self._company_id,
                account_id=account.account_id,
                marketplace=account.marketplace.value,
                display_name=account.display_name,
                credential_reference=account.credential_reference,
                active=account.active,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict("Channel account already exists for this company.")
        return account

    async def get(self, account_id: UUID) -> SalesChannelAccount | None:
        model = await self._session.scalar(
            select(SalesChannelConfigModel)
            .where(
                SalesChannelConfigModel.company_id == self._company_id,
                SalesChannelConfigModel.id == account_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _account(model)

    async def get_by_external_account(
        self, marketplace: Marketplace, account_id: UUID
    ) -> SalesChannelAccount | None:
        model = await self._session.scalar(
            select(SalesChannelConfigModel)
            .where(
                SalesChannelConfigModel.company_id == self._company_id,
                SalesChannelConfigModel.marketplace == marketplace.value,
                SalesChannelConfigModel.account_id == account_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _account(model)

    async def save(
        self,
        account: SalesChannelAccount,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> SalesChannelAccount:
        self._validate(account, actor_id)
        _validate_next_version(account.record_version, expected_version)
        current = await self.get(account.id)
        if (
            current is None
            or current.account_id != account.account_id
            or current.marketplace is not account.marketplace
        ):
            raise SalesChannelVersionConflictError(expected_version)
        result = await self._session.execute(
            update(SalesChannelConfigModel)
            .where(
                SalesChannelConfigModel.company_id == self._company_id,
                SalesChannelConfigModel.id == account.id,
                SalesChannelConfigModel.version == expected_version,
            )
            .values(
                display_name=account.display_name,
                credential_reference=account.credential_reference,
                active=account.active,
                version=account.record_version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(SalesChannelConfigModel.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise SalesChannelVersionConflictError(expected_version)
        return account

    def _validate(self, account: SalesChannelAccount, actor_id: UUID) -> None:
        if not isinstance(account, SalesChannelAccount):
            raise TypeError("account must be a SalesChannelAccount.")
        if account.company_id != self._company_id:
            raise SalesChannelScopeError("Channel account belongs to another company.")
        self._actor(actor_id)


class ChannelSkuMappingRepository(_TenantRepository):
    async def add(
        self, entry: ChannelSkuMappingEntry, *, actor_id: UUID
    ) -> ChannelSkuMappingEntry:
        self._validate(entry, actor_id)
        if entry.record_version != 1:
            raise ValueError("A new SKU mapping must start at version one.")
        await self._require_matching_account(entry)
        mapping = entry.mapping
        self._session.add(
            ExternalOrderMappingModel(
                id=entry.id,
                company_id=self._company_id,
                channel_config_id=entry.channel_config_id,
                account_id=mapping.account_id,
                marketplace=mapping.marketplace.value,
                listing_id=mapping.listing_id,
                variation_id=mapping.variation_id,
                external_sku=mapping.external_sku,
                product_id=mapping.product_id,
                active=entry.active,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict("SKU mapping conflicts with a channel or product.")
        return entry

    async def get(self, mapping_id: UUID) -> ChannelSkuMappingEntry | None:
        model = await self._session.scalar(
            select(ExternalOrderMappingModel)
            .where(
                ExternalOrderMappingModel.company_id == self._company_id,
                ExternalOrderMappingModel.id == mapping_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _mapping(model)

    async def get_by_listing(
        self,
        *,
        channel_config_id: UUID,
        listing_id: str,
        variation_id: str,
    ) -> ChannelSkuMappingEntry | None:
        model = await self._session.scalar(
            select(ExternalOrderMappingModel)
            .where(
                ExternalOrderMappingModel.company_id == self._company_id,
                ExternalOrderMappingModel.channel_config_id == channel_config_id,
                ExternalOrderMappingModel.listing_id == listing_id,
                ExternalOrderMappingModel.variation_id == variation_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _mapping(model)

    async def save(
        self,
        entry: ChannelSkuMappingEntry,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> ChannelSkuMappingEntry:
        self._validate(entry, actor_id)
        _validate_next_version(entry.record_version, expected_version)
        await self._require_matching_account(entry)
        current = await self.get(entry.id)
        if (
            current is None
            or current.channel_config_id != entry.channel_config_id
            or current.mapping.account_id != entry.mapping.account_id
            or current.mapping.marketplace is not entry.mapping.marketplace
            or current.mapping.listing_id != entry.mapping.listing_id
            or current.mapping.variation_id != entry.mapping.variation_id
        ):
            raise SalesChannelVersionConflictError(expected_version)
        result = await self._session.execute(
            update(ExternalOrderMappingModel)
            .where(
                ExternalOrderMappingModel.company_id == self._company_id,
                ExternalOrderMappingModel.id == entry.id,
                ExternalOrderMappingModel.version == expected_version,
            )
            .values(
                external_sku=entry.mapping.external_sku,
                product_id=entry.mapping.product_id,
                active=entry.active,
                version=entry.record_version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(ExternalOrderMappingModel.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise SalesChannelVersionConflictError(expected_version)
        return entry

    async def _require_matching_account(self, entry: ChannelSkuMappingEntry) -> None:
        account = await SalesChannelConfigRepository(
            self._session, company_id=self._company_id
        ).get(entry.channel_config_id)
        if (
            account is None
            or account.account_id != entry.mapping.account_id
            or account.marketplace is not entry.mapping.marketplace
        ):
            raise SalesChannelConflictError(
                "SKU mapping does not match its tenant-bound channel account."
            )

    def _validate(self, entry: ChannelSkuMappingEntry, actor_id: UUID) -> None:
        if not isinstance(entry, ChannelSkuMappingEntry):
            raise TypeError("entry must be a ChannelSkuMappingEntry.")
        if entry.mapping.company_id != self._company_id:
            raise SalesChannelScopeError("SKU mapping belongs to another company.")
        self._actor(actor_id)


class MultichannelSalesOrderRepository(_TenantRepository):
    async def ingest(
        self, order: MultichannelSalesOrder, *, actor_id: UUID
    ) -> ChannelOrderIngestion:
        self._validate(order, actor_id)
        if order.record_version != 1:
            raise ValueError("A new channel order must start at version one.")
        await self._require_channel_and_mappings(order, require_active=True)
        snapshot = order.snapshot
        statement = (
            postgresql_insert(ChannelSalesOrderModel)
            .values(
                id=order.id,
                company_id=self._company_id,
                channel_config_id=order.channel_config_id,
                account_id=snapshot.reference.account_id,
                marketplace=snapshot.reference.marketplace.value,
                external_order_id=snapshot.reference.external_order_id,
                status=snapshot.status.value,
                currency=snapshot.currency,
                merchandise_amount=snapshot.merchandise_amount,
                freight_amount=snapshot.freight_amount,
                discount_amount=snapshot.discount_amount,
                total_amount=snapshot.total_amount,
                items=_serialized_items(snapshot),
                source_payload_hash=order.source_fingerprint,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
            .on_conflict_do_nothing(constraint="uq_sales_order_external_identity")
            .returning(ChannelSalesOrderModel.id)
        )
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted_id is not None:
            return ChannelOrderIngestion(order, replayed=False)
        existing = await self.get_by_external_reference(snapshot.reference)
        if existing is None or existing.source_fingerprint != order.source_fingerprint:
            raise SalesChannelConflictError(
                "External order identity was replayed with a different normalized payload."
            )
        return ChannelOrderIngestion(existing, replayed=True)

    async def get(self, order_id: UUID) -> MultichannelSalesOrder | None:
        model = await self._session.scalar(
            select(ChannelSalesOrderModel)
            .where(
                ChannelSalesOrderModel.company_id == self._company_id,
                ChannelSalesOrderModel.id == order_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _order(model)

    async def get_by_external_reference(
        self, reference: ChannelOrderReference
    ) -> MultichannelSalesOrder | None:
        if reference.company_id != self._company_id:
            return None
        model = await self._session.scalar(
            select(ChannelSalesOrderModel)
            .where(
                ChannelSalesOrderModel.company_id == self._company_id,
                ChannelSalesOrderModel.marketplace == reference.marketplace.value,
                ChannelSalesOrderModel.account_id == reference.account_id,
                ChannelSalesOrderModel.external_order_id == reference.external_order_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _order(model)

    async def save(
        self,
        order: MultichannelSalesOrder,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> MultichannelSalesOrder:
        self._validate(order, actor_id)
        _validate_next_version(order.record_version, expected_version)
        current = await self.get(order.id)
        if (
            current is None
            or current.channel_config_id != order.channel_config_id
            or current.snapshot.reference != order.snapshot.reference
        ):
            raise SalesChannelVersionConflictError(expected_version)
        await self._require_channel_and_mappings(order, require_active=False)
        snapshot = order.snapshot
        result = await self._session.execute(
            update(ChannelSalesOrderModel)
            .where(
                ChannelSalesOrderModel.company_id == self._company_id,
                ChannelSalesOrderModel.id == order.id,
                ChannelSalesOrderModel.version == expected_version,
            )
            .values(
                status=snapshot.status.value,
                merchandise_amount=snapshot.merchandise_amount,
                freight_amount=snapshot.freight_amount,
                discount_amount=snapshot.discount_amount,
                total_amount=snapshot.total_amount,
                items=_serialized_items(snapshot),
                source_payload_hash=order.source_fingerprint,
                version=order.record_version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(ChannelSalesOrderModel.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise SalesChannelVersionConflictError(expected_version)
        return order

    async def _require_channel_and_mappings(
        self, order: MultichannelSalesOrder, *, require_active: bool
    ) -> None:
        account = await SalesChannelConfigRepository(
            self._session, company_id=self._company_id
        ).get(order.channel_config_id)
        reference = order.snapshot.reference
        if (
            account is None
            or account.account_id != reference.account_id
            or account.marketplace is not reference.marketplace
            or (require_active and not account.active)
        ):
            raise SalesChannelConflictError(
                "Order does not match an active tenant-bound channel account."
            )
        mappings = ChannelSkuMappingRepository(self._session, company_id=self._company_id)
        for item in order.snapshot.items:
            persisted = await mappings.get_by_listing(
                channel_config_id=order.channel_config_id,
                listing_id=item.mapping.listing_id,
                variation_id=item.mapping.variation_id,
            )
            if (
                persisted is None
                or not persisted.active
                or persisted.mapping != item.mapping
            ):
                raise SalesChannelConflictError(
                    "Order item has no active tenant-bound SKU mapping."
                )

    def _validate(self, order: MultichannelSalesOrder, actor_id: UUID) -> None:
        if not isinstance(order, MultichannelSalesOrder):
            raise TypeError("order must be a MultichannelSalesOrder.")
        if order.snapshot.reference.company_id != self._company_id:
            raise SalesChannelScopeError("Channel order belongs to another company.")
        self._actor(actor_id)


def _validate_next_version(record_version: int, expected_version: int) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise ValueError("expected_version must be a positive integer.")
    if record_version != expected_version + 1:
        raise ValueError("save requires exactly one new record version.")


__all__ = [
    "ChannelOrderIngestion",
    "ChannelSkuMappingRepository",
    "MultichannelSalesOrderRepository",
    "SalesChannelConfigRepository",
    "_account",
    "_mapping",
    "_order",
]
