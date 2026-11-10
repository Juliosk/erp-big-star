"""Commit 215 Sales/WMS cockpits, tenant isolation and responsive Chromium."""

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService, PermissionCode
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.sales.application import (
    SALES_ORDERS_READ,
    SalesAuthorization,
    SalesChannelPulse,
    SalesCockpitOrder,
    SalesCockpitService,
    SalesCockpitSnapshot,
)
from erp.modules.sales.infrastructure import PostgresSalesCockpitReader
from erp.modules.wms.application import (
    WMS_INVENTORY_READ,
    WmsAuthorization,
    WmsCockpitService,
    WmsCockpitSnapshot,
    WmsCockpitWave,
    WmsDispatchQueueEntry,
    WmsZoneOccupancy,
)
from erp.modules.wms.infrastructure import PostgresWmsCockpitReader
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_multichannel_order_ingestion import (
    _command,
    _payload,
    ingestion_fixture,
)
from tests.integration.test_multichannel_order_ingestion import (
    _service as ingestion_service,
)
from tests.integration.test_sales_quote_api import SalesApiFixture, sales_api
from tests.integration.test_wms_picking_packing_service import (
    _create_command,
    picking_packing_fixture,
)
from tests.integration.test_wms_picking_packing_service import (
    _service as picking_service,
)

pytestmark = pytest.mark.integration

TOKEN = "sales-wms-cockpit-token"
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)


class FixedCostProvider:
    async def standard_costs(
        self,
        company_id: UUID,
        product_ids: frozenset[UUID],
    ) -> dict[UUID, Decimal]:
        del company_id
        return {product_id: Decimal("10.00") for product_id in product_ids}


def test_postgres_cockpit_readers_use_real_multichannel_and_wms_models() -> None:
    async def scenario() -> None:
        async with ingestion_fixture() as sales_data:
            await ingestion_service(sales_data).ingest(
                sales_data.context,
                _command(sales_data, _payload()),
            )
            sales_snapshot = await PostgresSalesCockpitReader(
                sales_data.sales.database,
                FixedCostProvider(),
            ).load(sales_data.sales.company_id, as_of=NOW, limit=20)
            assert sales_snapshot.company_id == sales_data.sales.company_id
            assert sales_snapshot.orders[0].marketplace == "SHOPEE"
            assert sales_snapshot.orders[0].reconciliation_status == "RECONCILED"
            assert sales_snapshot.orders[0].margin_percent == Decimal("63.64")
            assert sales_snapshot.channels[1].order_count == 1
            assert sales_snapshot.margin_pending_orders == 0

        async with picking_packing_fixture() as wms_data:
            created = await picking_service(wms_data).create_wave(
                wms_data.context,
                _create_command(wms_data),
            )
            wms_snapshot = await PostgresWmsCockpitReader(
                wms_data.locations.database
            ).load(wms_data.locations.company_id, as_of=NOW, limit=20)
            assert wms_snapshot.company_id == wms_data.locations.company_id
            assert wms_snapshot.waves[0].id == created.wave.id
            assert wms_snapshot.waves[0].next_address == created.items[0].route_address
            assert wms_snapshot.dispatch_queue[0].pending_pick_items == 2
            assert wms_snapshot.zones[0].occupied_bins == 2
            assert wms_snapshot.total_bins >= 2

    asyncio.run(scenario())


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == TOKEN else None


@dataclass(frozen=True, slots=True)
class FixedSalesReader:
    owner_company_id: UUID

    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> SalesCockpitSnapshot:
        del limit
        if company_id != self.owner_company_id:
            return SalesCockpitSnapshot(company_id, as_of, _channels(), (), 0, 0)
        orders = (
            SalesCockpitOrder(
                uuid4(),
                "MLB-215-001",
                "MERCADO_LIVRE",
                "PAID",
                "RECONCILED",
                Decimal("149.90"),
                Decimal("54.90"),
                Decimal("36.62"),
                "LABEL_CREATED",
                "BR215TRACK",
                NOW,
            ),
            SalesCockpitOrder(
                uuid4(),
                "SHOPEE-215-002",
                "SHOPEE",
                "PENDING",
                "RECONCILED",
                Decimal("89.90"),
                None,
                None,
                None,
                None,
                NOW,
            ),
        )
        return SalesCockpitSnapshot(company_id, as_of, _channels(with_orders=True), orders, 2, 1)


def _channels(*, with_orders: bool = False) -> tuple[SalesChannelPulse, ...]:
    return (
        SalesChannelPulse(
            "MERCADO_LIVRE",
            1 if with_orders else 0,
            0,
            1 if with_orders else 0,
            0,
            0,
            Decimal("149.90") if with_orders else Decimal("0"),
            Decimal("54.90") if with_orders else Decimal("0"),
            Decimal("36.62") if with_orders else None,
            0,
        ),
        SalesChannelPulse(
            "SHOPEE",
            1 if with_orders else 0,
            1 if with_orders else 0,
            0,
            0,
            0,
            Decimal("89.90") if with_orders else Decimal("0"),
            None if with_orders else Decimal("0"),
            None,
            1 if with_orders else 0,
        ),
        SalesChannelPulse("NUVEMSHOP", 0, 0, 0, 0, 0, Decimal("0"), Decimal("0"), None, 0),
    )


@dataclass(frozen=True, slots=True)
class FixedWmsReader:
    owner_company_id: UUID

    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> WmsCockpitSnapshot:
        del limit
        if company_id != self.owner_company_id:
            return WmsCockpitSnapshot(company_id, as_of, (), (), (), 0, 0, Decimal("0"))
        wave_id = uuid4()
        return WmsCockpitSnapshot(
            company_id,
            as_of,
            (
                WmsCockpitWave(
                    wave_id,
                    "WAVE-215-A",
                    uuid4(),
                    "PACKING",
                    6,
                    6,
                    3,
                    Decimal("75.00"),
                    "PICK/A01/B01/L01/BIN01",
                    "PICK/A02/B02/L01/BIN03",
                    None,
                    NOW,
                ),
            ),
            (
                WmsZoneOccupancy(
                    uuid4(), "PICK", "PICKING", 24, 17, 1, 680, 960, Decimal("70.83")
                ),
                WmsZoneOccupancy(
                    uuid4(), "PULM", "BULK", 18, 8, 0, 310, 900, Decimal("34.44")
                ),
            ),
            (WmsDispatchQueueEntry(wave_id, "WAVE-215-A", "PACKING", 0, 3, 3, None),),
            42,
            1,
            Decimal("53.76"),
        )


def _context(
    fixture: SalesApiFixture,
    *,
    permissions: frozenset[PermissionCode] | None = None,
    company_id: UUID | None = None,
) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(
            fixture.data.actor_id,
            uuid4(),
            AuthenticationLevel.LEVEL_2,
        ),
        permissions=permissions
        or frozenset(
            {
                PermissionCode("admin.company.read"),
                SALES_ORDERS_READ,
                WMS_INVENTORY_READ,
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id or fixture.data.company_id)}),
    )


@dataclass(frozen=True, slots=True)
class BrowserServer:
    url: str
    fixture: SalesApiFixture
    resolver: ResolverStub


@contextmanager
def cockpit_server() -> Iterator[BrowserServer]:
    with sales_api() as fixture, socket.socket() as listener:
        settings = get_settings()
        database = Database(settings)
        resolver = ResolverStub()
        resolver.context = _context(fixture)
        companies = CompanyAccessService(PostgresCorporateDirectory(database))
        application = create_app(
            settings=settings,
            database=database,
            security_context_resolver=resolver,
            sales_channel_cockpit=SalesCockpitService(
                FixedSalesReader(fixture.data.company_id),
                SalesAuthorization(companies),
            ),
            wms_operations_cockpit=WmsCockpitService(
                FixedWmsReader(fixture.data.company_id),
                WmsAuthorization(companies),
            ),
        )
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Sales/WMS cockpit server failed to start.")
                time.sleep(0.02)
            yield BrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", fixture, resolver
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."


@pytest.mark.browser
def test_sales_and_wms_cockpits_chromium_desktop_mobile_rbac_and_tenant_scope() -> None:
    with cockpit_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        failures: list[str] = []

        sales_page = browser.new_page(viewport={"width": 1440, "height": 1050})
        sales_page.on("pageerror", lambda error: failures.append(str(error)))
        response = sales_page.goto(server.url + "/ui/sales/cockpit")
        assert response is not None
        assert response.ok
        sales_page.get_by_label("Token de acesso").fill(TOKEN)
        sales_page.get_by_role("button", name="Conectar aos canais").click()
        expect(sales_page.get_by_role("heading", name="Cockpit de canais")).to_be_visible()
        expect(sales_page.locator("#channels")).to_contain_text("Mercado Livre")
        expect(sales_page.locator("#channels")).to_contain_text("Margem comercial 36,62%")
        expect(sales_page.locator("#orders")).to_contain_text("MLB-215-001")
        expect(sales_page.locator("#orders")).to_contain_text("Custo M9 pendente")
        sales_page.screenshot(
            path=str(artifacts / "sales-marketplace-cockpit-desktop.png"), full_page=True
        )
        sales_page.set_viewport_size({"width": 390, "height": 844})
        assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        sales_page.screenshot(
            path=str(artifacts / "sales-marketplace-cockpit-mobile.png"), full_page=True
        )
        assert sales_page.evaluate("localStorage.length + sessionStorage.length") == 0

        wms_page = browser.new_page(viewport={"width": 1440, "height": 1050})
        wms_page.on("pageerror", lambda error: failures.append(str(error)))
        response = wms_page.goto(server.url + "/ui/wms/cockpit")
        assert response is not None
        assert response.ok
        wms_page.get_by_label("Token de acesso").fill(TOKEN)
        wms_page.get_by_role("button", name="Conectar ao armazém").click()
        expect(wms_page.get_by_role("heading", name="Torre do armazém")).to_be_visible()
        expect(wms_page.locator("#zones")).to_contain_text("ZONA PICK")
        expect(wms_page.locator("#waves")).to_contain_text("WAVE-215-A")
        expect(wms_page.locator("#dispatch-queue")).to_contain_text("3 para conferir")
        wms_page.screenshot(
            path=str(artifacts / "wms-operations-cockpit-desktop.png"), full_page=True
        )
        wms_page.set_viewport_size({"width": 390, "height": 844})
        assert wms_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        wms_page.screenshot(
            path=str(artifacts / "wms-operations-cockpit-mobile.png"), full_page=True
        )
        assert wms_page.evaluate("localStorage.length + sessionStorage.length") == 0

        headers = {"Authorization": f"Bearer {TOKEN}"}
        hidden = wms_page.request.get(
            server.url
            + f"/api/v1/wms/cockpit?company_id={server.fixture.data.other_company_id}",
            headers=headers,
        )
        assert hidden.status == 404

        server.resolver.context = _context(
            server.fixture,
            company_id=server.fixture.data.other_company_id,
        )
        isolated = wms_page.request.get(
            server.url
            + f"/api/v1/wms/cockpit?company_id={server.fixture.data.other_company_id}",
            headers=headers,
        )
        assert isolated.ok
        assert isolated.json()["waves"] == []

        server.resolver.context = _context(
            server.fixture,
            permissions=frozenset({PermissionCode("admin.company.read")}),
        )
        denied = browser.new_page(viewport={"width": 1024, "height": 768})
        denied.goto(server.url + "/ui/wms/cockpit")
        denied.get_by_label("Token de acesso").fill(TOKEN)
        denied.get_by_role("button", name="Conectar ao armazém").click()
        expect(
            denied.get_by_role("heading", name="Permissão de inventário WMS necessária")
        ).to_be_visible()
        forbidden = denied.request.get(
            server.url
            + f"/api/v1/sales/cockpit?company_id={server.fixture.data.company_id}",
            headers=headers,
        )
        assert forbidden.status == 403
        assert failures == []
        browser.close()


def test_cockpit_assets_keep_tokens_ephemeral_and_use_official_contracts() -> None:
    sales_root = Path("erp/apps/web/static/sales/cockpit")
    wms_root = Path("erp/apps/web/static/wms/cockpit")
    sales_script = (sales_root / "cockpit.js").read_text(encoding="utf-8")
    wms_script = (wms_root / "cockpit.js").read_text(encoding="utf-8")
    assert "sales.orders.read" in sales_script
    assert "sales/cockpit?company_id=" in sales_script
    assert "wms.inventory.read" in wms_script
    assert "wms/cockpit?company_id=" in wms_script
    assert "localStorage" not in sales_script + wms_script
    assert "sessionStorage" not in sales_script + wms_script
    assert "ChannelSalesOrderModel" not in sales_script
    assert "WmsPickingWaveModel" not in wms_script


__all__: list[str] = []
