"""Commit 211: multichannel parsing, idempotency, M5 hold and Outbox proofs."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from erp.modules.admin.contracts import CompanyAccessService, SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Branch,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.domain import Warehouse
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryReservationAllocationModel,
    InventoryReservationModel,
    WarehouseModel,
    WarehouseRepository,
)
from erp.modules.marketplace.infrastructure import (
    ChannelOAuthCredentials,
    ChannelOAuthToken,
    HomologationMarketplaceTransport,
    InMemoryChannelCredentialStore,
    MarketplaceGatewayAdapter,
)
from erp.modules.sales.application import (
    SALES_CHANNELS_INGEST,
    CommandMetadata,
    IngestMultichannelOrder,
    MultichannelOrderIngestionService,
    SalesAuthorization,
)
from erp.modules.sales.domain import (
    ChannelOrderReference,
    ChannelSkuMapping,
    ChannelSkuMappingEntry,
    Marketplace,
    SalesChannelAccount,
)
from erp.modules.sales.infrastructure import (
    ChannelSalesOrderModel,
    ChannelSkuMappingRepository,
    PostgresMultichannelOrderIngestion,
    SalesChannelConfigRepository,
)
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_product_persistence import _cnpj
from tests.integration.test_sales_repository import SalesFixture, sales_fixture

pytestmark = pytest.mark.integration


class CompanyAccessStub:
    async def require_company(
        self, context: SecurityContext, company_id: UUID, *, write: bool = False
    ) -> None:
        assert company_id in {scope.scope_id for scope in context.scopes}
        assert write


@dataclass(frozen=True, slots=True)
class IngestionFixture:
    sales: SalesFixture
    account: SalesChannelAccount
    mapping: ChannelSkuMappingEntry
    warehouse_id: UUID
    context: SecurityContext


@asynccontextmanager
async def ingestion_fixture() -> AsyncIterator[IngestionFixture]:
    async with sales_fixture() as sales:
        account = SalesChannelAccount.create(
            company_id=sales.company_id,
            account_id=uuid4(),
            marketplace=Marketplace.SHOPEE,
            display_name="Shopee homologation",
            credential_reference="secret://sales/shopee/homologation",
        )
        mapping = ChannelSkuMappingEntry.create(
            channel_config_id=account.id,
            mapping=ChannelSkuMapping(
                company_id=sales.company_id,
                account_id=account.account_id,
                marketplace=Marketplace.SHOPEE,
                listing_id="10001",
                variation_id="20001",
                external_sku="SHOPEE-SKU-01",
                product_id=sales.product.id,
            ),
        )
        branch = Branch.create(
            company_id=sales.company_id,
            code=f"MC{uuid4().hex[:6].upper()}",
            name="Multichannel branch",
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        warehouse = Warehouse.create(
            company_id=sales.company_id,
            branch_id=branch.id,
            code=f"MC{uuid4().hex[:6].upper()}",
            name="Multichannel warehouse",
        )
        async with sales.database.session() as session, session.begin():
            await BranchRepository().add(session, branch, actor_id=sales.actor_id)
            await WarehouseRepository(session, company_id=sales.company_id).add(
                warehouse, actor_id=sales.actor_id
            )
            await SalesChannelConfigRepository(session, company_id=sales.company_id).add(
                account, actor_id=sales.actor_id
            )
            await ChannelSkuMappingRepository(session, company_id=sales.company_id).add(
                mapping, actor_id=sales.actor_id
            )
            session.add(
                InventoryBalanceModel(
                    id=uuid4(),
                    company_id=sales.company_id,
                    product_id=sales.product.id,
                    warehouse_id=warehouse.id,
                    location_id=None,
                    lot_id=None,
                    pool_id=None,
                    state="AVAILABLE",
                    quantity=Decimal("10.000000"),
                    version=1,
                )
            )
        context = SecurityContext(
            principal=AuthenticatedPrincipal(sales.actor_id, uuid4(), AuthenticationLevel.LEVEL_2),
            permissions=frozenset({SALES_CHANNELS_INGEST}),
            scopes=frozenset({Scope(ScopeType.COMPANY, sales.company_id)}),
        )
        try:
            yield IngestionFixture(sales, account, mapping, warehouse.id, context)
        finally:
            async with sales.database.session() as session, session.begin():
                await session.execute(
                    delete(InventoryReservationAllocationModel).where(
                        InventoryReservationAllocationModel.company_id == sales.company_id
                    )
                )
                await session.execute(
                    delete(InventoryReservationModel).where(
                        InventoryReservationModel.company_id == sales.company_id
                    )
                )
                await session.execute(
                    delete(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == sales.company_id
                    )
                )
                await session.execute(
                    delete(WarehouseModel).where(WarehouseModel.company_id == sales.company_id)
                )
                await session.execute(
                    delete(BranchModel).where(BranchModel.company_id == sales.company_id)
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.payload["company_id"].as_string() == str(sales.company_id)
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.company_id == sales.company_id)
                )


def _payload(*, sku: str = "SHOPEE-SKU-01", quantity: str = "2.000000") -> dict[str, object]:
    return {
        "ordersn": "SHOPEE-ORDER-211",
        "order_status": "READY_TO_SHIP",
        "currency": "BRL",
        "item_list": [
            {
                "order_item_id": "LINE-1",
                "item_id": "10001",
                "model_id": "20001",
                "model_sku": sku,
                "model_quantity_purchased": quantity,
                "model_discounted_price": "25.00",
            }
        ],
        "freight_amount": "7.00",
        "discount_amount": "2.00",
        "commission_fee": "3.00",
        "service_fee": "0.50",
    }


def _service(data: IngestionFixture) -> MultichannelOrderIngestionService:
    gateway = MarketplaceGatewayAdapter(
        Marketplace.SHOPEE,
        InMemoryChannelCredentialStore({}),
        HomologationMarketplaceTransport({}),
    )
    return MultichannelOrderIngestionService(
        PostgresMultichannelOrderIngestion(data.sales.database),
        SalesAuthorization(cast(CompanyAccessService, CompanyAccessStub())),
        {Marketplace.SHOPEE: gateway},
    )


def _command(data: IngestionFixture, payload: Mapping[str, object]) -> IngestMultichannelOrder:
    correlation_id = uuid4()
    return IngestMultichannelOrder(
        company_id=data.sales.company_id,
        channel_config_id=data.account.id,
        marketplace=Marketplace.SHOPEE,
        external_order_id="SHOPEE-ORDER-211",
        warehouse_id=data.warehouse_id,
        idempotency_key="commit-211-shopee-order",
        metadata=CommandMetadata(correlation_id, correlation_id, "127.0.0.1"),
        payload=payload,
    )


def test_ingestion_reserves_stock_emits_events_and_replays_once() -> None:
    async def scenario() -> None:
        async with ingestion_fixture() as data:
            service = _service(data)
            command = _command(data, _payload())
            first = await service.ingest(data.context, command)
            replay = await service.ingest(data.context, command)

            assert not first.replayed
            assert first.event_id is not None
            assert first.inventory_event_id is not None
            assert first.audit_event_id is not None
            assert first.inventory_audit_event_id is not None
            assert first.order.id == replay.order.id
            assert first.reservation.id == replay.reservation.id
            assert first.reservation.reference_id == first.order.id
            assert first.reservation.reference_type == "SALES_ORDER"
            assert first.fees == replay.fees
            assert sum((fee.amount for fee in first.fees), Decimal("0")) == Decimal("3.50")
            assert replay.replayed
            assert replay.event_id is None

            async with data.sales.database.session() as session:
                order_count = await session.scalar(
                    select(func.count())
                    .select_from(ChannelSalesOrderModel)
                    .where(ChannelSalesOrderModel.company_id == data.sales.company_id)
                )
                reservation_count = await session.scalar(
                    select(func.count())
                    .select_from(InventoryReservationModel)
                    .where(InventoryReservationModel.company_id == data.sales.company_id)
                )
                event_types = set(
                    await session.scalars(
                        select(OutboxEventModel.event_type).where(
                            OutboxEventModel.payload["company_id"].as_string()
                            == str(data.sales.company_id)
                        )
                    )
                )
            assert order_count == 1
            assert reservation_count == 1
            assert event_types == {
                "InventoryReservationCreated",
                "MarketplaceOrderApproved",
            }

    asyncio.run(scenario())


def test_unmapped_sku_rolls_back_order_reservation_and_effects() -> None:
    async def scenario() -> None:
        async with ingestion_fixture() as data:
            with pytest.raises(ApplicationError) as captured:
                await _service(data).ingest(
                    data.context, _command(data, _payload(sku="UNKNOWN-SKU"))
                )
            assert captured.value.code == "CHANNEL_SKU_NOT_MAPPED"

            async with data.sales.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ChannelSalesOrderModel)
                        .where(ChannelSalesOrderModel.company_id == data.sales.company_id)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InventoryReservationModel)
                        .where(InventoryReservationModel.company_id == data.sales.company_id)
                    )
                    == 0
                )

    asyncio.run(scenario())


def test_insufficient_inventory_rolls_back_order_and_outbox() -> None:
    async def scenario() -> None:
        async with ingestion_fixture() as data:
            with pytest.raises(ApplicationError) as captured:
                await _service(data).ingest(
                    data.context, _command(data, _payload(quantity="11.000000"))
                )
            assert captured.value.code == "INVENTORY_RESERVATION_CONFLICT"

            async with data.sales.database.session() as session:
                order_count = await session.scalar(
                    select(func.count())
                    .select_from(ChannelSalesOrderModel)
                    .where(ChannelSalesOrderModel.company_id == data.sales.company_id)
                )
                reservation_count = await session.scalar(
                    select(func.count())
                    .select_from(InventoryReservationModel)
                    .where(InventoryReservationModel.company_id == data.sales.company_id)
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.payload["company_id"].as_string()
                        == str(data.sales.company_id)
                    )
                )
            assert order_count == 0
            assert reservation_count == 0
            assert event_count == 0

    asyncio.run(scenario())


def test_channel_adapters_normalize_three_dialects_and_refresh_oauth() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        account_id = uuid4()
        now = datetime(2026, 11, 9, tzinfo=UTC)
        payloads: dict[Marketplace, dict[str, object]] = {
            Marketplace.MERCADO_LIVRE: {
                "id": "ML-1",
                "status": "paid",
                "order_items": [
                    {
                        "id": "ML-LINE",
                        "item": {
                            "id": "MLB1",
                            "variation_id": "STD",
                            "seller_sku": "SKU-ML",
                        },
                        "quantity": "1.000000",
                        "unit_price": "10.00",
                        "sale_fee": "1.00",
                    }
                ],
            },
            Marketplace.SHOPEE: {
                "ordersn": "SH-1",
                "order_status": "READY_TO_SHIP",
                "item_list": [
                    {
                        "item_id": "SH1",
                        "model_id": "STD",
                        "model_sku": "SKU-SH",
                        "model_quantity_purchased": "1.000000",
                        "model_discounted_price": "10.00",
                    }
                ],
            },
            Marketplace.NUVEMSHOP: {
                "id": "NV-1",
                "status": "paid",
                "products": [
                    {
                        "id": "NV1",
                        "variant_id": "STD",
                        "sku": "SKU-NV",
                        "quantity": "1.000000",
                        "price": "10.00",
                    }
                ],
                "fees": [{"type": "GATEWAY", "amount": "0.75"}],
            },
        }
        for marketplace, payload in payloads.items():
            external_id = {
                Marketplace.MERCADO_LIVRE: "ML-1",
                Marketplace.SHOPEE: "SH-1",
                Marketplace.NUVEMSHOP: "NV-1",
            }[marketplace]
            reference_key = f"secret://{marketplace.value.lower()}"
            credentials = InMemoryChannelCredentialStore(
                {
                    reference_key: ChannelOAuthCredentials(
                        "client-id",
                        "client-secret",
                        ChannelOAuthToken(
                            "expired-access",
                            "refresh-token",
                            now - timedelta(minutes=1),
                        ),
                    )
                }
            )
            assert "client-secret" not in repr(await credentials.get(reference_key))
            assert "expired-access" not in repr(await credentials.get(reference_key))
            transport = HomologationMarketplaceTransport(
                {(marketplace, external_id): payload}, now=now
            )
            gateway = MarketplaceGatewayAdapter(marketplace, credentials, transport, now=now)
            normalized = await gateway.fetch_order(
                ChannelOrderReference(company_id, account_id, marketplace, external_id),
                reference_key,
            )
            assert normalized.reference.external_order_id == external_id
            assert normalized.items[0].external_sku.startswith("SKU-")
            assert transport.refresh_count == 1
            assert transport.fetch_count == 1

    asyncio.run(scenario())


__all__: list[str] = []
