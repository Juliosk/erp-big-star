"""Inventory UI through Chromium, real HTTP, dev auth and PostgreSQL."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr
from sqlalchemy import select

from erp.apps.api.app import create_app
from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchRepository
from erp.modules.inventory.infrastructure import InventoryBalanceModel
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_inventory_api import InventoryApiFixture, inventory_api
from tests.integration.test_product_persistence import _cnpj

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class InventoryBrowserServer:
    url: str
    token: str
    fixture: InventoryApiFixture


@contextmanager
def inventory_browser_server() -> Iterator[InventoryBrowserServer]:
    with inventory_api() as fixture, socket.socket() as listener:
        token = "inventory-browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=fixture.data.actor_id,
            dev_auth_company_ids=(fixture.data.company_id, fixture.data.other_company_id),
        )
        settings = Settings.model_validate(values)
        database = Database(settings)
        application = create_app(settings, database)
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Inventory browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield InventoryBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, fixture
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_inventory_web_balances_adjustments_trace_and_company_isolation() -> None:
    with inventory_browser_server() as server:

        async def seed() -> tuple[str, str]:
            branch = Branch.create(
                company_id=server.fixture.data.company_id,
                code="WEBINV",
                name="Inventory web branch",
                tax_id=_cnpj(),
                timezone="America/Sao_Paulo",
            )
            product = server.fixture.data.product(code="WEBINV")
            async with server.fixture.data.database.session() as session, session.begin():
                await BranchRepository().add(session, branch, actor_id=server.fixture.data.actor_id)
                await ProductRepository(session, company_id=server.fixture.data.company_id).add(
                    product, actor_id=server.fixture.data.actor_id
                )
            return str(branch.id), str(product.id)

        assert server.fixture.client.portal is not None
        branch_id, product_id = server.fixture.client.portal.call(seed)
        warehouse = server.fixture.client.post(
            "/api/v1/inventory/warehouses",
            json={
                "company_id": str(server.fixture.data.company_id),
                "branch_id": branch_id,
                "code": "WEB-WH",
                "name": "Depósito Web",
            },
            headers=server.fixture.headers,
        )
        assert warehouse.status_code == 201
        warehouse_id = warehouse.json()["id"]
        lot = server.fixture.client.post(
            "/api/v1/inventory/lots",
            json={
                "company_id": str(server.fixture.data.company_id),
                "product_id": product_id,
                "code": "WEB-LOT",
            },
            headers=server.fixture.headers,
        )
        assert lot.status_code == 201
        lot_id = lot.json()["id"]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            failures: list[str] = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(server.url + "/ui/")
            page.get_by_label("Token de acesso").fill(server.token)
            page.get_by_role("button", name="Conectar", exact=True).click()
            expect(page.get_by_role("heading", name="Catálogo de produtos")).to_be_visible()
            expect(page.locator("#inventory-nav")).to_be_visible()
            page.locator("#company").select_option(str(server.fixture.data.company_id))
            page.locator("#inventory-nav").click()
            expect(page.get_by_role("heading", name="Inventário")).to_be_visible()
            expect(page.locator("#inventory-warehouse-rows")).to_contain_text("WEB-WH")
            expect(page.locator("#inventory-lot-rows")).to_contain_text("WEB-LOT")
            expect(page.locator("#inventory-empty")).to_be_visible()

            page.locator("#inventory-product-id").fill(product_id)
            page.locator("#inventory-warehouse-id").select_option(warehouse_id)
            page.locator("#inventory-lot-id").select_option(lot_id)
            page.locator("#inventory-adjustment-quantity").fill("7.25")
            page.locator("#inventory-adjustment-reason").fill("Ajuste inicial via Chromium")
            page.get_by_role("button", name="Registrar ajuste", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Ajuste registrado")
            expect(page.locator("#inventory-balance-rows")).to_contain_text("7.250000")
            expect(page.locator("#inventory-balance-rows")).to_contain_text("v1")
            page.locator("#inventory-trace-lot-id").select_option(lot_id)
            expect(page.locator("#inventory-trace-rows")).to_contain_text("7.250000")

            artifacts = Path("test-results")
            artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts / "inventory-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(artifacts / "inventory-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator("#company").select_option(str(server.fixture.data.other_company_id))
            expect(page.locator("#inventory-empty")).to_be_visible()
            expect(page.locator("#inventory-balance-rows tr")).to_have_count(0)
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            assert failures == []
            browser.close()

        async def verify_effects() -> None:
            async with server.fixture.data.database.session() as session:
                balance = await session.scalar(
                    select(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == server.fixture.data.company_id,
                        InventoryBalanceModel.warehouse_id == UUID(warehouse_id),
                        InventoryBalanceModel.lot_id == UUID(lot_id),
                    )
                )
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.source_module == "inventory",
                        OutboxEventModel.event_type == "InventoryAdjusted",
                    )
                )
                assert balance is not None
                assert f"{balance.quantity:.6f}" == "7.250000"
                assert balance.version == 1
                assert outbox is not None
                assert outbox.event_type == "InventoryAdjusted"

        server.fixture.client.portal.call(verify_effects)
