"""Inbound fiscal reconciliation journey through Chromium and real PostgreSQL."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr
from sqlalchemy import select

from erp.apps.api.app import create_app
from erp.modules.inventory.infrastructure.balance_model import InventoryBalanceModel
from erp.modules.procurement.infrastructure import GoodsReceiptModel
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from tests.integration.test_fiscal_physical_reconciliation import (
    _inspected_receipt,
    _xml,
    reconciliation_api,
)

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class InboundBrowserServer:
    url: str
    token: str
    api: Any
    receipt_id: UUID
    receipt_item_id: UUID
    product_id: UUID
    supplier_tax_id: str


@contextmanager
def inbound_browser_server() -> Iterator[InboundBrowserServer]:
    with reconciliation_api() as (api, warehouse, issued, supplier), socket.socket() as listener:
        receipt = _inspected_receipt(api, warehouse, issued)
        token = "inbound-browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=api.data.actor_id,
            dev_auth_company_ids=(api.data.company_id,),
        )
        settings = Settings.model_validate(values)
        application = create_app(settings, Database(settings))
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Inbound browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield InboundBrowserServer(
                url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token=token,
                api=api,
                receipt_id=UUID(receipt.json()["id"]),
                receipt_item_id=UUID(receipt.json()["items"][0]["id"]),
                product_id=UUID(receipt.json()["items"][0]["product_id"]),
                supplier_tax_id=supplier.json()["identity_value"],
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_inbound_mde_reconciliation_posts_available_through_cockpit() -> None:
    with inbound_browser_server() as server, sync_playwright() as playwright:
        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        xml_path = artifacts / f"nfe-fornecedor-{uuid4().hex}.xml"
        xml_path.write_text(_xml(server.supplier_tax_id), encoding="utf-8")
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.locator("#fiscal-nav").click()
        expect(page.get_by_role("heading", name="Cockpit fiscal")).to_be_visible()
        page.get_by_role("tab", name="Entradas e conciliação").click()
        expect(page.locator("#fiscal-inbound-view")).to_be_visible()
        assert failures == []

        page.locator("#fiscal-inbound-file").set_input_files(xml_path)
        page.locator("#fiscal-inbound-upload-form button").click()
        expect(page.locator("#notice")).to_contain_text("XML de entrada importado")
        xml_path.unlink()
        expect(page.locator("#fiscal-inbound-title")).to_contain_text("NF-e")
        expect(page.locator("#fiscal-inbound-status")).to_have_text("Pendente")

        page.locator("#fiscal-mde-event").select_option("210200")
        page.get_by_role("button", name="Transmitir manifestação", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("210200")
        expect(page.locator("#fiscal-inbound-status")).to_have_text("Operação confirmada")
        expect(page.locator("#fiscal-mde-history")).to_contain_text("210200")

        page.locator("#fiscal-receipt").select_option(str(server.receipt_id))
        page.get_by_label("Item físico para linha fiscal 1").select_option(
            str(server.receipt_item_id)
        )
        page.get_by_role("button", name="Conciliar e liberar estoque", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Saldo AVAILABLE lançado")
        expect(page.locator("#fiscal-reconciliation-status")).to_have_text("Conciliado e lançado")
        expect(page.locator("#fiscal-reconciliation-issues")).to_contain_text("Sem inconsistências")
        expect(page.locator("#fiscal-financial-flag")).to_have_text("Financeiro liberado")

        page.screenshot(path=str(artifacts / "inbound-reconciliation-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "inbound-reconciliation-mobile.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()

        async def verify() -> tuple[str, str]:
            async with server.api.data.database.session() as session:
                receipt = await session.scalar(
                    select(GoodsReceiptModel).where(GoodsReceiptModel.id == server.receipt_id)
                )
                balance = await session.scalar(
                    select(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == server.api.data.company_id,
                        InventoryBalanceModel.product_id == server.product_id,
                        InventoryBalanceModel.state == "AVAILABLE",
                    )
                )
                assert receipt is not None
                assert balance is not None
                return receipt.status, str(balance.quantity)

        assert server.api.client.portal is not None
        assert server.api.client.portal.call(verify) == ("POSTED", "10.000000")
