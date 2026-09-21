"""Sales Cockpit E2E through Chromium, real HTTP and PostgreSQL."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr
from sqlalchemy import update

from erp.apps.api.app import create_app
from erp.modules.inventory.application.commands import (
    CommandMetadata as InventoryCommandMetadata,
)
from erp.modules.inventory.application.commands import (
    ExpireInventoryReservations,
)
from erp.modules.inventory.infrastructure import (
    InventoryReservationModel,
    PostgresInventoryReservations,
)
from erp.modules.sales.infrastructure import PostgresSalesOrderReservations
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from tests.integration.test_sales_order_reservations import (
    _cleanup_reservations,
    _create_order,
    _seed_stock_and_approve,
)
from tests.integration.test_sales_quote_api import SalesApiFixture, sales_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class SalesBrowserServer:
    url: str
    token: str
    fixture: SalesApiFixture


@contextmanager
def sales_browser_server() -> Iterator[SalesBrowserServer]:
    with sales_api() as api, socket.socket() as listener:
        assert api.client.portal is not None
        token = "sales-browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=api.data.actor_id,
            dev_auth_company_ids=(api.data.company_id, api.data.other_company_id),
            dev_auth_permissions=(
                "admin.company.read",
                "product.product.read",
                "sales.quote.create",
                "sales.quote.read",
                "sales.quote.update",
                "sales.quote.send",
                "sales.quote.convert",
                "sales.discount.request",
                "sales.order.create",
                "sales.order.read",
                "sales.order.reserve",
                "sales.order.cancel",
                "inventory.availability.read",
                "inventory.warehouse.read",
                "workflow.definition.manage",
                "workflow.request.create",
            ),
        )
        settings = Settings.model_validate(values)
        database = Database(settings)
        application = create_app(settings, database)
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(application, log_config=None, log_level="warning")
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Sales browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield SalesBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, api
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."
            api.client.portal.call(_cleanup_reservations, api)


def test_sales_cockpit_quote_discount_and_order_flow() -> None:
    with sales_browser_server() as server, sync_playwright() as playwright:
        assert server.fixture.client.portal is not None
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        headers = {"Authorization": f"Bearer {server.token}"}

        definition = page.request.post(
            server.url + "/api/v1/workflow/definitions",
            headers=headers,
            data={
                "company_id": str(server.fixture.data.company_id),
                "code": "SALES-DISCOUNT-WEB",
                "name": "Alçada comercial web",
                "source_module": "SALES",
                "source_type": "QUOTE_DISCOUNT",
                "approval_mode": "SEQUENTIAL",
                "steps": [
                    {
                        "sequence": 1,
                        "code": "MANAGER",
                        "name": "Gerência comercial",
                        "required_permission": "workflow.approval.decide",
                        "threshold_amount": "1.00",
                    }
                ],
            },
        )
        assert definition.ok

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.locator("#sales-nav")).to_be_visible()
        page.locator("#company").select_option(str(server.fixture.data.company_id))
        page.locator("#sales-nav").click()
        expect(page.get_by_role("heading", name="Cockpit comercial")).to_be_visible()

        page.locator("#sales-quote-number").fill("COT-E2E-001")
        page.locator("#sales-customer-id").fill(server.fixture.customer_id)
        page.get_by_role("button", name="Criar cotação", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Cotação criada")
        expect(page.locator("#sales-selected-title")).to_have_text("COT-E2E-001")

        page.locator("#sales-product-id").fill(server.fixture.product_id)
        page.locator("#sales-quantity").fill("2.500000")
        page.locator("#sales-unit-price").fill("40.00")
        page.locator("#sales-discount").fill("10.00")
        page.get_by_role("button", name="Salvar revisão", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Revisão comercial salva")
        expect(page.locator("#sales-totals")).to_contain_text("R$ 90,00")

        page.get_by_role("button", name="Solicitar aprovação de desconto", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Aprovação de desconto solicitada")
        page.get_by_role("button", name="Enviar cotação", exact=True).click()
        expect(page.locator("#sales-selected-meta")).to_contain_text("Enviada")
        page.get_by_role("button", name="Aceitar", exact=True).click()
        expect(page.locator("#sales-selected-meta")).to_contain_text("Aceita")

        page.locator("#sales-order-number").fill("PED-E2E-001")
        page.get_by_role("button", name="Converter em pedido", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Pedido criado")
        expect(page.locator("#sales-order-rows")).to_contain_text("PED-E2E-001")
        expect(page.locator("#sales-selected-meta")).to_contain_text("Convertida")

        orders = page.request.get(
            server.url
            + f"/api/v1/sales/orders?company_id={server.fixture.data.company_id}",
            headers=headers,
        ).json()["data"]
        first_order_id = UUID(next(item["id"] for item in orders if item["number"] == "PED-E2E-001"))
        warehouse_id = server.fixture.client.portal.call(
            _seed_stock_and_approve, server.fixture, (first_order_id,)
        )
        page.locator("#sales-refresh").click()
        first_row = page.locator("#sales-order-rows tr", has_text="PED-E2E-001")
        first_row.get_by_role("button", name="Gerir").click()
        expect(page.locator("#sales-order-title")).to_have_text("PED-E2E-001")
        page.locator("#sales-warehouse").select_option(str(warehouse_id))
        expect(page.locator("#sales-available")).to_have_text("5")
        expect(page.locator("#sales-required")).to_have_text("2,5")
        page.get_by_role("button", name="Solicitar reserva", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Reserva física confirmada")
        expect(page.locator("#sales-reservation-status")).to_have_text("Reserva ativa")
        expect(page.locator("#sales-hold-clock")).not_to_have_text("—")
        expect(page.locator("#sales-available")).to_have_text("2,5")
        page.get_by_role("button", name="Estender hold +2h", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Hold estendido")
        page.get_by_role("button", name="Cancelar pedido e liberar", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("reserva física liberada")
        expect(page.locator("#sales-reservation-status")).to_have_text("Liberada")
        expect(page.locator("#sales-available")).to_have_text("5")

        expiring_order, _ = _create_order(
            server.fixture, suffix="E2E-EXPIRE", quantity="1.000000"
        )
        expiry_warehouse = server.fixture.client.portal.call(
            _seed_stock_and_approve, server.fixture, (expiring_order,)
        )
        page.locator("#sales-refresh").click()
        expiring_row = page.locator("#sales-order-rows tr", has_text="SO-RES-E2E-EXPIRE")
        expiring_row.get_by_role("button", name="Gerir").click()
        page.locator("#sales-warehouse").select_option(str(expiry_warehouse))
        page.locator("#sales-hold-hours").select_option("1")
        page.get_by_role("button", name="Solicitar reserva", exact=True).click()
        expect(page.locator("#sales-reservation-status")).to_have_text("Reserva ativa")
        expiring_reservation_id = UUID(
            page.request.get(
                server.url
                + f"/api/v1/sales/orders/{expiring_order}/reservation?company_id={server.fixture.data.company_id}",
                headers=headers,
            ).json()["inventory_reservation_id"]
        )

        async def expire_hold() -> None:
            expired_at = datetime.now(UTC)
            async with server.fixture.data.database.session() as session, session.begin():
                await session.execute(
                    update(InventoryReservationModel)
                    .where(
                        InventoryReservationModel.company_id == server.fixture.data.company_id,
                        InventoryReservationModel.id == expiring_reservation_id,
                    )
                    .values(expires_at=expired_at)
                )
            now = datetime.now(UTC)
            trace_id = uuid4()
            result = await PostgresInventoryReservations(
                server.fixture.data.database, ttl_seconds=86_400
            ).expire_due(
                ExpireInventoryReservations(
                    company_id=server.fixture.data.company_id,
                    now=now,
                    batch_size=10,
                    idempotency_key=f"browser-expire-{expiring_reservation_id}",
                    metadata=InventoryCommandMetadata(trace_id, trace_id, "127.0.0.1"),
                ),
                server.fixture.data.actor_id,
            )
            assert [item.id for item in result.expired] == [expiring_reservation_id]
            await PostgresSalesOrderReservations(
                server.fixture.data.database, ttl_seconds=86_400
            ).synchronize_expiration(
                server.fixture.data.company_id,
                expiring_order,
                server.fixture.data.actor_id,
            )

        server.fixture.client.portal.call(expire_hold)
        page.locator("#sales-refresh").click()
        expiring_row = page.locator("#sales-order-rows tr", has_text="SO-RES-E2E-EXPIRE")
        expiring_row.get_by_role("button", name="Gerir").click()
        expect(page.locator("#sales-reservation-status")).to_have_text("Expirada")
        expect(page.locator("#sales-hold-clock")).to_have_text("Expirada")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "sales-inventory-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "sales-inventory-cockpit-mobile.png"), full_page=True)

        page.locator("#company").select_option(str(server.fixture.data.other_company_id))
        expect(page.locator("#sales-empty")).to_be_visible()
        expect(page.locator("#sales-quote-rows tr")).to_have_count(0)
        expect(page.locator("#sales-order-rows tr")).to_have_count(0)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()
