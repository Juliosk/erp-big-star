"""Sales Cockpit E2E through Chromium, real HTTP and PostgreSQL."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr

from erp.apps.api.app import create_app
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
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


def test_sales_cockpit_quote_discount_and_order_flow() -> None:
    with sales_browser_server() as server, sync_playwright() as playwright:
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

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "sales-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "sales-cockpit-mobile.png"), full_page=True)

        page.locator("#company").select_option(str(server.fixture.data.other_company_id))
        expect(page.locator("#sales-empty")).to_be_visible()
        expect(page.locator("#sales-quote-rows tr")).to_have_count(0)
        expect(page.locator("#sales-order-rows tr")).to_have_count(0)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()
