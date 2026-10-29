"""Bank-reconciliation cockpit journeys through a real Chromium browser."""

import re
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.domain import PermissionCode
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_bank_conciliation_api import (
    _ofx,
    reconciliation_api,
)
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True, slots=True)
class ReconciliationBrowserServer:
    url: str
    token: str
    data: ProcurementFixture


@contextmanager
def reconciliation_browser_server() -> Iterator[ReconciliationBrowserServer]:
    with reconciliation_api() as (_, data, resolver, _, _), socket.socket() as listener:
        assert resolver.context is not None
        resolver.context = replace(
            resolver.context,
            permissions=resolver.context.permissions | {PermissionCode("admin.company.read")},
        )
        settings = get_settings()
        application = create_app(
            settings=settings,
            database=Database(settings),
            security_context_resolver=resolver,
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
                    raise RuntimeError(
                        "Bank reconciliation browser test HTTP server failed to start."
                    )
                time.sleep(0.02)
            yield ReconciliationBrowserServer(
                url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token="bank-reconciliation-test-token",
                data=data,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_bank_conciliation_cockpit_upload_match_and_direct_fee() -> None:
    with reconciliation_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        response = page.goto(server.url + "/ui/finance/conciliation")
        assert response is not None
        assert response.ok
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.wait_for_timeout(500)
        assert failures == []
        expect(page.get_by_role("heading", name="Mesa de conciliação")).to_be_visible()
        expect(page.locator("#conciliation-nav")).to_be_visible()

        account_id = uuid4()
        page.get_by_label("Conta bancária (UUID)").fill(str(account_id))
        page.get_by_label("Banco", exact=True).fill("001")
        page.get_by_label("Agência / conta").fill("1234 / 56789-0")
        page.locator("#conciliation-file").set_input_files(
            {
                "name": "statement-185.ofx",
                "mimeType": "application/x-ofx",
                "buffer": _ofx(),
            }
        )
        page.get_by_role("button", name="Importar extrato", exact=True).click()
        expect(page.locator("#conciliation-import-status")).to_contain_text(
            "importado com 2 movimentos"
        )
        expect(page.locator("#conciliation-movement-list")).to_contain_text("Pagamento fornecedor")
        expect(page.locator("#conciliation-movement-list")).to_contain_text("Tarifa bancaria")

        page.get_by_role("button", name="Pagamento fornecedor", exact=False).click()
        expect(page.locator("#conciliation-explanation-title")).to_have_text("Sugestão exata")
        expect(page.locator("#conciliation-candidate-list")).to_contain_text("PAY-API-183")
        expect(page.locator("#conciliation-accept")).to_be_visible()
        page.get_by_role("button", name="Aceitar sugestão", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Movimento conciliado")
        expect(page.locator("#conciliation-matched-count")).to_have_text("1")

        page.get_by_role("button", name="Tarifa bancaria", exact=False).click()
        expect(page.locator("#conciliation-match-signal")).to_have_class(
            re.compile(r"\bDIRECT_FEE\b")
        )
        page.get_by_role("button", name="Classificar lançamento direto", exact=True).click()
        expect(page.locator("#conciliation-resolution-dialog")).to_be_visible()
        page.locator("#conciliation-justification").fill(
            "Tarifa bancária confirmada no extrato oficial da conta."
        )
        page.get_by_role("button", name="Confirmar resolução", exact=True).click()
        expect(page.locator("#conciliation-resolution-dialog")).to_be_hidden()
        expect(page.locator("#notice")).to_contain_text("Classificação direta confirmada")
        expect(page.locator("#conciliation-matched-count")).to_have_text("1")
        expect(page.locator("#conciliation-match-signal")).to_have_class(
            re.compile(r"\bDIRECT_FEE\b")
        )

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(
            path=str(artifacts / "bank-conciliation-cockpit-desktop.png"),
            full_page=True,
        )
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(
            path=str(artifacts / "bank-conciliation-cockpit-mobile.png"),
            full_page=True,
        )
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()


def test_bank_conciliation_assets_keep_clean_architecture_contract() -> None:
    html = Path("erp/apps/web/static/index.html").read_text(encoding="utf-8")
    script = Path("erp/apps/web/static/conciliation.js").read_text(encoding="utf-8")
    mount = Path("erp/apps/web/mount.py").read_text(encoding="utf-8")
    assert "Mesa de conciliação" in html
    assert "DECISÃO EXPLICÁVEL" in html
    assert 'can("finance.reconciliation.execute")' in script
    assert "finance/reconciliation/statements" in script
    assert "BankStatementModel" not in script
    assert '"finance/conciliation"' in mount


__all__: list[str] = []
