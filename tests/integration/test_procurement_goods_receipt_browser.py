"""Real Chromium journey for the M6/M17/M5 physical receiving cockpit."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.domain import PermissionCode
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_procurement_goods_receipt_api import (
    _issued_order,
    goods_receipt_api,
)

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class ReceiptBrowserServer:
    url: str
    token: str
    company_id: str
    warehouse_id: str
    order_number: str


@contextmanager
def receipt_browser_server() -> Iterator[ReceiptBrowserServer]:
    with goods_receipt_api() as (fixture, warehouse), socket.socket() as listener:
        issued = _issued_order(fixture)
        token = "purchasing-test-token"
        assert fixture.resolver.context is not None
        fixture.resolver.context = replace(
            fixture.resolver.context,
            permissions=fixture.resolver.context.permissions
            | {
                PermissionCode("admin.company.read"),
                PermissionCode("procurement.supplier.read"),
            },
        )
        application = create_app(
            settings=get_settings(),
            database=Database(get_settings()),
            security_context_resolver=fixture.resolver,
        )
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
                    raise RuntimeError("Goods receipt browser server failed to start.")
                time.sleep(0.02)
            yield ReceiptBrowserServer(
                url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token=token,
                company_id=str(fixture.data.company_id),
                warehouse_id=str(warehouse.id),
                order_number=issued.json()["number"],
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."


def test_goods_receipt_cockpit_full_physical_journey() -> None:
    with receipt_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.locator("#company").select_option(server.company_id)
        page.locator("#procurement-nav").click()
        expect(page.get_by_role("heading", name="Conferência física")).to_be_visible()
        page.locator("#procurement-receipt-number").fill("REC-E2E-0143")
        page.locator("#procurement-receipt-order").select_option(
            label=server.order_number
        )
        page.locator("#procurement-receipt-warehouse").fill(server.warehouse_id)
        page.locator("#procurement-receipt-quantity").fill("10")
        page.get_by_role("button", name="Registrar conferência cega").click()
        expect(page.locator("#notice")).to_contain_text("Conferência cega registrada")

        card = page.locator(".receipt-card", has_text="REC-E2E-0143")
        card.get_by_role("button", name="Confirmar chegada").click()
        expect(page.locator("#notice")).to_contain_text("Etapa do recebimento concluída")
        card.get_by_role("button", name="Aprovar inspeção M17").click()
        expect(card).to_contain_text("Inspecionado")
        card.get_by_role("button", name="Postar no estoque M5").click()
        expect(page.locator("#notice")).to_contain_text("Saldo físico atualizado no M5")
        expect(card).to_contain_text("Lançado no estoque")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "goods-receipt-cockpit.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        assert failures == []
        browser.close()
