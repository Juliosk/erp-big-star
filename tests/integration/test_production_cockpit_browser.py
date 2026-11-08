"""Production cockpit API and responsive Chromium behavior."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import update

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
from erp.modules.production.application import (
    PRODUCTION_SHOP_FLOOR_READ,
    ProductionAuthorization,
    ProductionCockpitService,
)
from erp.modules.production.domain import WorkCenterCode
from erp.modules.production.infrastructure import (
    PostgresProductionCockpitReader,
    PostgresProductionEngineeringDirectory,
    ProductionEventConsumer,
    ProductionOrderRepository,
    RoutingOperationModel,
    RoutingRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.messaging import MessageEnvelope, MessageKind
from tests.integration.test_planned_order_conversion import (
    AS_OF,
    ConversionFixture,
    _command,
    _conversion_service,
)
from tests.integration.test_production_event_consumers import production_event_fixture

pytestmark = pytest.mark.integration

TOKEN = "production-cockpit-test-token"
STARTED_AT = datetime(2026, 11, 8, 9, tzinfo=UTC)


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == TOKEN else None


@dataclass(frozen=True, slots=True)
class ProductionCockpitFixture:
    client: TestClient
    data: ConversionFixture
    resolver: ResolverStub
    production_order_id: UUID


@contextmanager
def production_cockpit_api() -> Iterator[ProductionCockpitFixture]:
    resolver = ResolverStub()
    settings = get_settings()
    with TestClient(create_app(settings, security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = production_event_fixture()
        data = client.portal.call(manager.__aenter__)
        service = ProductionCockpitService(
            PostgresProductionCockpitReader(data.production.database),
            ProductionAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(data.production.database))
            ),
        )
        application = cast(FastAPI, client.app)
        application.state.production_cockpit = service
        resolver.context = _context(data)
        order_id = client.portal.call(_seed_active_order, data)
        try:
            yield ProductionCockpitFixture(client, data, resolver, order_id)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def _context(
    data: ConversionFixture,
    *,
    company_id: UUID | None = None,
    permissions: frozenset[PermissionCode] | None = None,
) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(
            data.production.actor_id,
            uuid4(),
            AuthenticationLevel.LEVEL_1,
        ),
        permissions=permissions
        or frozenset(
            {
                PRODUCTION_SHOP_FLOOR_READ,
                PermissionCode("admin.company.read"),
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id or data.production.company_id)}),
    )


async def _seed_active_order(data: ConversionFixture) -> UUID:
    company_id = data.production.company_id
    async with data.production.database.session() as session, session.begin():
        converted = await _conversion_service(data, session).convert(
            _command(data, data.manufacture_order_id),
            actor_id=data.production.actor_id,
        )
        engineering = await PostgresProductionEngineeringDirectory(
            session, company_id=company_id
        ).resolve(
            company_id=company_id,
            product_id=data.production.finished.id,
            version_code="R1",
            effective_on=AS_OF,
        )
        assert engineering is not None
        released = converted.production_order.release(
            bom=engineering.bom,
            routing=engineering.routing,
            actor_id=data.production.actor_id,
            occurred_at=STARTED_AT,
        )
        orders = ProductionOrderRepository(session, company_id=company_id)
        await orders.save(
            released,
            actor_id=data.production.actor_id,
            expected_version=converted.production_order.record_version,
        )
        center = await RoutingRepository(session, company_id=company_id).get_work_center(
            WorkCenterCode("MRP-CELL")
        )
        assert center is not None
        started = released.start_operation(
            10,
            work_center=center,
            actor_id=data.production.actor_id,
            occurred_at=STARTED_AT,
        )
        await orders.save(
            started,
            actor_id=data.production.actor_id,
            expected_version=released.record_version,
        )
        await session.execute(
            update(RoutingOperationModel)
            .where(RoutingOperationModel.company_id == company_id)
            .values(run_minutes_per_unit=Decimal("100"))
        )

    event = MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="InventoryAdjusted",
        event_version=1,
        producer_module="inventory",
        producer_domain="inventory",
        aggregate_type="inventory_adjustment",
        aggregate_id=uuid4(),
        aggregate_version=1,
        company_id=company_id,
        branch_id=None,
        occurred_at=STARTED_AT,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "company_id": str(company_id),
            "postings": [{"product_id": str(data.production.raw_material.id)}],
        },
    )
    await ProductionEventConsumer(data.production.database).consume(event)
    return started.id


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_production_cockpit_api_is_tenant_bound_rbac_protected_and_event_aware() -> None:
    with production_cockpit_api() as fixture:
        response = fixture.client.get(
            "/api/v1/production/cockpit",
            headers=_headers(),
            params={"company_id": str(fixture.data.production.company_id)},
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["company_id"] == str(fixture.data.production.company_id)
        assert body["orders"][0]["id"] == str(fixture.production_order_id)
        assert body["orders"][0]["status"] == "IN_PROGRESS"
        assert body["orders"][0]["last_synchronization_at"] is not None
        assert body["work_centers"][0]["code"] == "MRP-CELL"
        assert Decimal(body["work_centers"][0]["load_percent"]) > 100
        assert {value["alert_type"] for value in body["alerts"]} >= {"WORK_CENTER_LOAD"}

        fixture.resolver.context = _context(
            fixture.data,
            permissions=frozenset({PermissionCode("admin.company.read")}),
        )
        denied = fixture.client.get(
            "/api/v1/production/cockpit",
            headers=_headers(),
            params={"company_id": str(fixture.data.production.company_id)},
        )
        assert denied.status_code == 403

        fixture.resolver.context = _context(
            fixture.data,
            company_id=fixture.data.production.other_company_id,
        )
        hidden = fixture.client.get(
            "/api/v1/production/cockpit",
            headers=_headers(),
            params={"company_id": str(fixture.data.production.other_company_id)},
        )
        assert hidden.status_code == 200
        assert hidden.json()["orders"] == []


@dataclass(frozen=True, slots=True)
class BrowserServer:
    url: str
    fixture: ProductionCockpitFixture


@contextmanager
def production_cockpit_browser_server() -> Iterator[BrowserServer]:
    with production_cockpit_api() as fixture, socket.socket() as listener:
        settings = get_settings()
        browser_database = Database(settings)
        application = create_app(
            settings=settings,
            database=browser_database,
            security_context_resolver=fixture.resolver,
            production_cockpit=ProductionCockpitService(
                PostgresProductionCockpitReader(browser_database),
                ProductionAuthorization(
                    CompanyAccessService(
                        PostgresCorporateDirectory(browser_database)
                    )
                ),
            ),
        )
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level="warning"))
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Production cockpit HTTP server failed to start.")
                time.sleep(0.02)
            yield BrowserServer(f"http://127.0.0.1:{listener.getsockname()[1]}", fixture)
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."


@pytest.mark.browser
def test_production_cockpit_chromium_desktop_mobile_and_rbac_navigation() -> None:
    with production_cockpit_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        response = page.goto(server.url + "/ui/production/cockpit")
        assert response is not None
        assert response.ok
        page.get_by_label("Token de acesso").fill(TOKEN)
        page.get_by_role("button", name="Conectar à produção").click()

        expect(page.get_by_role("heading", name="Cockpit industrial")).to_be_visible()
        expect(page.locator(".center-card")).to_contain_text("MRP-CELL")
        expect(page.locator(".center-card")).to_contain_text("Gargalo")
        expect(page.locator("#orders")).to_contain_text("Em execução")
        expect(page.locator("#orders")).to_contain_text("Atualizada")
        expect(page.locator("#alerts")).to_contain_text("Carga elevada")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "production-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("heading", name="Cockpit industrial")).to_be_visible()
        overflow = page.locator("body *").evaluate_all(
            """elements => elements.filter(element => {
              const style = getComputedStyle(element);
              return element.getBoundingClientRect().right > window.innerWidth + 1
                && style.overflowX !== 'auto';
            }).slice(0, 10).map(element => ({tag: element.tagName, id: element.id}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "production-cockpit-mobile.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0

        server.fixture.resolver.context = replace(
            cast(SecurityContext, server.fixture.resolver.context),
            permissions=frozenset({PermissionCode("admin.company.read")}),
        )
        denied = browser.new_page(viewport={"width": 1024, "height": 768})
        denied.goto(server.url + "/ui/production/cockpit")
        denied.get_by_label("Token de acesso").fill(TOKEN)
        denied.get_by_role("button", name="Conectar à produção").click()
        expect(
            denied.get_by_role("heading", name="Permissão de chão de fábrica necessária")
        ).to_be_visible()
        assert failures == []
        browser.close()


def test_production_cockpit_assets_keep_the_clean_web_contract() -> None:
    root = Path("erp/apps/web/static/production/cockpit")
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "cockpit.js").read_text(encoding="utf-8")
    assert "ANDON DIGITAL" in html
    assert "production.shop_floor.read" in script
    assert "production/cockpit?company_id=" in script
    assert "ProductionOrderModel" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


__all__: list[str] = []
