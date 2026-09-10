"""Chromium E2E for M14 customer management and Customer 360."""

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
from tests.integration.customer_api_support import CustomerApiFixture, customer_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class CustomerBrowserServer:
    url: str
    token: str
    fixture: CustomerApiFixture


@contextmanager
def customer_browser_server() -> Iterator[CustomerBrowserServer]:
    with customer_api() as fixture, socket.socket() as listener:
        token = "browser-" + uuid4().hex
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
                    raise RuntimeError("Customer browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield CustomerBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, fixture
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_customer_web_vertical_slice_group_360_duplicate_and_company_isolation() -> None:
    with customer_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.get_by_role("heading", name="Catálogo de produtos")).to_be_visible()
        page.locator("#company").select_option(str(server.fixture.data.company_id))
        page.locator("#customers-nav").click()
        expect(page.get_by_role("heading", name="Clientes", exact=True)).to_be_visible()
        expect(page.locator("#customers-empty")).to_be_visible()

        page.get_by_role("button", name="+ Novo cliente", exact=True).click()
        create_dialog = page.locator("#customer-create-dialog")
        create_dialog.get_by_label("CPF/CNPJ", exact=True).fill("52998224725")
        create_dialog.get_by_label("Razão social / Nome", exact=True).fill("Maria Souza")
        create_dialog.get_by_label("Nome fantasia", exact=True).fill("Maria Brinquedos")
        create_dialog.get_by_role("button", name="Criar cliente", exact=True).click()
        expect(page.locator("#customer-detail-title")).to_have_text("Maria Souza")
        expect(page.locator("#customer-detail-meta")).to_contain_text("Versão 1")
        page.locator("#customer-detail").get_by_label("Razão social / Nome", exact=True).fill(
            "Maria Souza Kids"
        )
        page.locator("#customer-status").select_option("BLOCKED")
        page.get_by_role("button", name="Salvar cliente", exact=True).click()
        expect(page.locator("#customer-detail-title")).to_have_text("Maria Souza Kids")
        expect(page.locator("#customer-detail-meta")).to_contain_text("Versão 3")
        expect(page.locator("#customer-detail-status")).to_contain_text("Bloqueado")

        page.locator("#back-customers").click()
        page.get_by_role("button", name="Grupos", exact=True).click()
        page.get_by_role("button", name="+ Novo grupo", exact=True).click()
        group_dialog = page.locator("#group-create-dialog")
        group_dialog.get_by_label("Código do grupo", exact=True).fill("vip-web")
        group_dialog.get_by_label("Nome do grupo", exact=True).fill("VIP Web")
        group_dialog.get_by_label("Descrição do grupo", exact=True).fill("Segmento criado no E2E")
        group_dialog.get_by_role("button", name="Criar grupo", exact=True).click()
        expect(page.locator("#customer-group-rows")).to_contain_text("VIP-WEB")

        page.locator("#back-customers-from-groups").click()
        page.get_by_role("button", name="+ Novo cliente", exact=True).click()
        create_dialog.get_by_label("CPF/CNPJ", exact=True).fill("15350946056")
        create_dialog.get_by_label("Razão social / Nome", exact=True).fill("Maria Souza Kidz")
        create_dialog.get_by_label("Nome fantasia", exact=True).fill("Maria S.")
        create_dialog.get_by_role("button", name="Criar cliente", exact=True).click()
        expect(page.locator("#customer-detail-title")).to_have_text("Maria Souza Kidz")

        page.locator("#back-customers").click()
        page.get_by_role("button", name="Abrir 360 de Maria Souza Kids").click()
        expect(page.locator("#customer-assign-group option")).to_have_count(2)
        group_value = page.locator("#customer-assign-group option").nth(1).get_attribute("value")
        assert group_value
        page.locator("#customer-assign-group").select_option(group_value)
        expect(page.locator("#customer-assign-group")).to_have_value(group_value)
        with page.expect_response(
            lambda response: response.url.endswith("/groups") and response.request.method == "POST"
        ) as assigned:
            page.get_by_role("button", name="Vincular grupo", exact=True).click()
        assert assigned.value.status == 201, (
            assigned.value.request.post_data,
            assigned.value.json(),
        )
        expect(page.locator("#customer-group-list")).to_contain_text("VIP-WEB")
        page.get_by_role("button", name="Verificar duplicidades", exact=True).click()
        expect(page.locator("#customer-merge-list")).to_contain_text("confiança")
        page.get_by_role("button", name="Solicitar mesclagem", exact=True).click()
        expect(page.locator("#customer-merge-list")).to_contain_text("PENDING_APPROVAL")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "customer-360-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifacts / "customer-360-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator("#company").select_option(str(server.fixture.data.other_company_id))
        expect(page.locator("#customers-empty")).to_be_visible()
        expect(page.locator("#customer-rows tr")).to_have_count(0)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()
