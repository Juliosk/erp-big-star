"""Fiscal Cockpit full journey through Chromium and real PostgreSQL."""

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
from tests.integration.test_fiscal_document_api import FiscalApiFixture, fiscal_api
from tests.integration.test_fiscal_document_download_api import MemoryArtifactStorage

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class FiscalBrowserServer:
    url: str
    token: str
    fixture: FiscalApiFixture


@contextmanager
def fiscal_browser_server() -> Iterator[FiscalBrowserServer]:
    with fiscal_api() as api, socket.socket() as listener:
        token = "fiscal-browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=api.data.actor_id,
            dev_auth_company_ids=(api.data.company_id, api.data.other_company_id),
        )
        settings = Settings.model_validate(values)
        application = create_app(
            settings,
            Database(settings),
            fiscal_artifact_storage=MemoryArtifactStorage(),
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
                    raise RuntimeError("Fiscal browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield FiscalBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, api
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_fiscal_cockpit_authorization_artifacts_and_cancellation() -> None:
    with fiscal_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.locator("#fiscal-nav")).to_be_visible()
        page.locator("#company").select_option(str(server.fixture.data.company_id))
        page.locator("#fiscal-nav").click()
        expect(page.get_by_role("heading", name="Cockpit fiscal")).to_be_visible()

        page.locator("#fiscal-number").fill("151")
        page.locator("#fiscal-product-id").fill(str(uuid4()))
        page.get_by_role("button", name="Criar rascunho", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Rascunho fiscal criado")
        expect(page.locator("#fiscal-selected-status")).to_have_text("Rascunho")

        page.get_by_role("button", name="Solicitar emissão", exact=True).click()
        expect(page.locator("#fiscal-selected-status")).to_have_text("Em transmissão")
        page.locator("#fiscal-contingency").select_option("SVC_AN")
        page.get_by_role("button", name="Processar retorno SEFAZ", exact=True).click()
        expect(page.locator("#fiscal-selected-status")).to_have_text("Autorizado")
        expect(page.locator("#fiscal-selected-meta")).to_contain_text("Protocolo")
        expect(page.locator("#fiscal-history")).to_contain_text("100")

        page.get_by_role("button", name="Visualizar DANFE", exact=True).click()
        expect(page.locator("#fiscal-danfe-preview")).to_be_visible()
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Baixar XML", exact=True).click()
        assert download_info.value.suggested_filename == "fiscal-151.xml"

        page.locator("#fiscal-cancel-reason").fill(
            "Cancelamento do documento no cenário E2E homologado"
        )
        page.get_by_role("button", name="Cancelar NF", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("110111")
        expect(page.locator("#fiscal-selected-status")).to_have_text("Cancelado")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "fiscal-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "fiscal-cockpit-mobile.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()
