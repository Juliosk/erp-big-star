"""PostgreSQL integration coverage for external sales channel persistence."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect

from erp.modules.product.domain import Product
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.sales.domain import (
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
from erp.modules.sales.infrastructure import (
    ChannelSalesOrderModel,
    ChannelSkuMappingRepository,
    ExternalOrderMappingModel,
    MultichannelSalesOrderRepository,
    SalesChannelConfigModel,
    SalesChannelConfigRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration
D = Decimal
DEFAULT_FREIGHT = D("5.00")


@dataclass(frozen=True)
class SalesFixture:
    data: Fixture
    product: Product
    replacement_product: Product

    @property
    def company_id(self) -> UUID:
        return self.data.company_id

    @property
    def other_company_id(self) -> UUID:
        return self.data.other_company_id

    @property
    def actor_id(self) -> UUID:
        return self.data.actor_id

    @property
    def database(self) -> Database:
        return self.data.database


@asynccontextmanager
async def sales_fixture() -> AsyncIterator[SalesFixture]:
    async with fixture() as data:
        product = data.product(code=f"CHANNEL-{uuid4().hex[:8].upper()}")
        replacement = data.product(code=f"CHANNEL-{uuid4().hex[:8].upper()}")
        async with data.database.session() as session, session.begin():
            repository = ProductRepository(session, company_id=data.company_id)
            await repository.add(product, actor_id=data.actor_id)
            await repository.add(replacement, actor_id=data.actor_id)
        try:
            yield SalesFixture(data, product, replacement)
        finally:
            company_ids = (data.company_id, data.other_company_id)
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(ChannelSalesOrderModel).where(
                        ChannelSalesOrderModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(ExternalOrderMappingModel).where(
                        ExternalOrderMappingModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(SalesChannelConfigModel).where(
                        SalesChannelConfigModel.company_id.in_(company_ids)
                    )
                )


def _account(data: SalesFixture) -> SalesChannelAccount:
    return SalesChannelAccount.create(
        company_id=data.company_id,
        account_id=uuid4(),
        marketplace=Marketplace.SHOPEE,
        display_name="Shopee principal",
        credential_reference="secret://sales/shopee/principal",
    )


def _mapping(
    data: SalesFixture,
    account: SalesChannelAccount,
    *,
    product_id: UUID | None = None,
) -> ChannelSkuMappingEntry:
    return ChannelSkuMappingEntry.create(
        channel_config_id=account.id,
        mapping=ChannelSkuMapping(
            company_id=data.company_id,
            account_id=account.account_id,
            marketplace=account.marketplace,
            listing_id="MLB-LISTING-01",
            variation_id="COLOR-BLUE",
            external_sku="SKU-EXTERNAL-01",
            product_id=product_id or data.product.id,
        ),
    )


def _order(
    data: SalesFixture,
    account: SalesChannelAccount,
    mapping: ChannelSkuMappingEntry,
    *,
    external_order_id: str = "ORDER-EXT-0001",
    freight: Decimal = DEFAULT_FREIGHT,
) -> MultichannelSalesOrder:
    reference = ChannelOrderReference(
        company_id=data.company_id,
        account_id=account.account_id,
        marketplace=account.marketplace,
        external_order_id=external_order_id,
    )
    return MultichannelSalesOrder.capture(
        channel_config_id=account.id,
        snapshot=ChannelOrderSnapshot(
            reference=reference,
            status=ChannelOrderStatus.PENDING,
            items=(
                ChannelOrderItem(
                    external_item_id="LINE-1",
                    mapping=mapping.mapping,
                    quantity=D("2.000000"),
                    unit_price=D("10.00"),
                    discount_amount=D("1.00"),
                ),
            ),
            freight_amount=freight,
            discount_amount=D("2.00"),
        ),
    )


def test_channel_configuration_mapping_and_order_round_trip() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            account = _account(data)
            mapping = _mapping(data, account)
            order = _order(data, account, mapping)
            async with data.database.session() as session, session.begin():
                configs = SalesChannelConfigRepository(session, company_id=data.company_id)
                mappings = ChannelSkuMappingRepository(session, company_id=data.company_id)
                orders = MultichannelSalesOrderRepository(
                    session, company_id=data.company_id
                )
                assert await configs.add(account, actor_id=data.actor_id) == account
                assert await mappings.add(mapping, actor_id=data.actor_id) == mapping
                result = await orders.ingest(order, actor_id=data.actor_id)
                assert not result.replayed
                assert result.order == order
                assert await configs.get_by_external_account(
                    account.marketplace, account.account_id
                ) == account
                assert await mappings.get(mapping.id) == mapping
                assert await orders.get(order.id) == order
                assert await orders.get_by_external_reference(order.snapshot.reference) == order

    asyncio.run(scenario())


def test_external_order_ingestion_is_idempotent_and_rejects_payload_drift() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            account = _account(data)
            mapping = _mapping(data, account)
            order = _order(data, account, mapping)
            replay = replace(order, id=uuid4())
            drifted = _order(data, account, mapping, freight=D("6.00"))
            async with data.database.session() as session, session.begin():
                await SalesChannelConfigRepository(
                    session, company_id=data.company_id
                ).add(account, actor_id=data.actor_id)
                await ChannelSkuMappingRepository(
                    session, company_id=data.company_id
                ).add(mapping, actor_id=data.actor_id)
                repository = MultichannelSalesOrderRepository(
                    session, company_id=data.company_id
                )
                first = await repository.ingest(order, actor_id=data.actor_id)
                second = await repository.ingest(replay, actor_id=data.actor_id)
                assert not first.replayed
                assert second.replayed
                assert second.order.id == order.id
                with pytest.raises(SalesChannelConflictError) as captured:
                    await repository.ingest(drifted, actor_id=data.actor_id)
                assert captured.value.code == "SALES_CHANNEL_CONFLICT"
                assert await repository.get(order.id) == order

    asyncio.run(scenario())


def test_tenant_scope_composite_keys_and_optimistic_versions() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            account = _account(data)
            mapping = _mapping(data, account)
            order = _order(data, account, mapping)
            async with data.database.session() as session, session.begin():
                configs = SalesChannelConfigRepository(session, company_id=data.company_id)
                mappings = ChannelSkuMappingRepository(session, company_id=data.company_id)
                orders = MultichannelSalesOrderRepository(
                    session, company_id=data.company_id
                )
                await configs.add(account, actor_id=data.actor_id)
                await mappings.add(mapping, actor_id=data.actor_id)
                await orders.ingest(order, actor_id=data.actor_id)

                foreign_orders = MultichannelSalesOrderRepository(
                    session, company_id=data.other_company_id
                )
                assert await foreign_orders.get(order.id) is None
                assert (
                    await foreign_orders.get_by_external_reference(order.snapshot.reference)
                    is None
                )
                with pytest.raises(SalesChannelScopeError):
                    await foreign_orders.ingest(order, actor_id=data.actor_id)

                updated = order.revise(
                    order.snapshot.transition(ChannelOrderStatus.PAID)
                )
                assert await orders.save(
                    updated, actor_id=data.actor_id, expected_version=1
                ) == updated
                with pytest.raises(SalesChannelVersionConflictError) as captured:
                    await orders.save(updated, actor_id=data.actor_id, expected_version=1)
                assert captured.value.code == "VERSION_CONFLICT"

                inactive = account.set_active(False)
                assert await configs.save(
                    inactive, actor_id=data.actor_id, expected_version=1
                ) == inactive
                remapped = mapping.remap(data.replacement_product.id)
                assert await mappings.save(
                    remapped, actor_id=data.actor_id, expected_version=1
                ) == remapped

    asyncio.run(scenario())


def test_composite_product_reference_and_caller_transaction_boundary() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            account = _account(data)
            invalid = _mapping(data, account, product_id=uuid4())
            async with data.database.session() as session, session.begin():
                configs = SalesChannelConfigRepository(session, company_id=data.company_id)
                await configs.add(account, actor_id=data.actor_id)
                nested = await session.begin_nested()
                with pytest.raises(SalesChannelConflictError):
                    await ChannelSkuMappingRepository(
                        session, company_id=data.company_id
                    ).add(invalid, actor_id=data.actor_id)
                await nested.rollback()

            rollback_account = replace(account, id=uuid4(), account_id=uuid4())
            async with data.database.session() as session:
                await SalesChannelConfigRepository(
                    session, company_id=data.company_id
                ).add(rollback_account, actor_id=data.actor_id)
                await session.rollback()
            async with data.database.session() as session:
                assert (
                    await SalesChannelConfigRepository(
                        session, company_id=data.company_id
                    ).get(rollback_account.id)
                    is None
                )

    asyncio.run(scenario())


def test_migration_0057_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="sales"))
                    expected_tables = {
                        "sales_channel_config",
                        "external_order_mapping",
                        "sales_order",
                    }
                    assert expected_tables.issubset(tables) is expected
                    if not expected:
                        return
                    constraints = {
                        value["name"]
                        for value in inspector.get_unique_constraints(
                            "sales_order", schema="sales"
                        )
                    }
                    assert "uq_sales_order_external_identity" in constraints
                    foreign_keys = inspector.get_foreign_keys(
                        "external_order_mapping", schema="sales"
                    )
                    assert any(
                        value["constrained_columns"]
                        == ["company_id", "channel_config_id"]
                        for value in foreign_keys
                    )

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0056")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0057")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []
