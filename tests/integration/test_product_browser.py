"""Chromium -> real HTTP -> development auth -> PostgreSQL, with isolated fixtures."""

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
from sqlalchemy import select

from erp.apps.api.app import create_app
from erp.apps.api.import_composition import compose_imports
from erp.modules.product.infrastructure import ProductModel, ProductRepository
from erp.platform.audit import AuditEventModel
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel
from erp.platform.storage import ObjectStorage
from tests.integration.product_api_support import ApiFixture, product_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class BrowserServer:
    url: str
    token: str
    fixture: ApiFixture


@contextmanager
def browser_server(
    *, read_only: bool = False, import_storage: ObjectStorage | None = None
) -> Iterator[BrowserServer]:
    with product_api() as fixture, socket.socket() as listener:
        token = "browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=fixture.data.actor_id,
            dev_auth_company_ids=(fixture.data.company_id, fixture.data.other_company_id),
        )
        if read_only:
            values["dev_auth_permissions"] = ("admin.company.read", "product.product.read")
        settings = Settings.model_validate(values)
        if import_storage is not None:
            settings = settings.model_copy(
                update={
                    "dev_auth_permissions": (
                        *settings.dev_auth_permissions,
                        "data.import.execute",
                        "data.import.confirm",
                    )
                }
            )
        database = Database(settings)
        application = create_app(settings, database)
        if import_storage is not None:
            application.state.imports = compose_imports(database, settings, import_storage)
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield BrowserServer(f"http://127.0.0.1:{listener.getsockname()[1]}", token, fixture)
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_web_vertical_slice_create_edit_barcode_lifecycle_and_company_isolation() -> None:
    with browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.get_by_role("heading", name="Catálogo de produtos")).to_be_visible()
        expect(page.locator("#dev-banner")).to_be_visible()
        page.locator("#company").select_option(str(server.fixture.data.company_id))
        expect(page.locator("#empty")).to_be_visible()
        page.get_by_role("button", name="+ Novo produto", exact=True).click()
        page.get_by_label("Código", exact=True).fill("BST-2401")
        page.get_by_label("SKU", exact=True).fill("BST-2401-AZ")
        page.get_by_label("Nome do produto", exact=True).fill("Caminhão de aventuras")
        page.get_by_role("button", name="Criar produto", exact=True).click()
        expect(page.locator("#detail-title")).to_have_text("Caminhão de aventuras")
        expect(page.locator("#detail-version")).to_have_text("Versão 1")
        page.get_by_label("Nome", exact=True).fill("Caminhão de aventuras azul")
        page.get_by_role("button", name="Salvar alterações").click()
        expect(page.locator("#detail-version")).to_have_text("Versão 2")

        # A second client changes the same row while this screen still holds ETag 2.
        headers = {"Authorization": f"Bearer {server.token}"}
        products = page.request.get(
            f"{server.url}/api/v1/products?company_id={server.fixture.data.company_id}",
            headers=headers,
        ).json()
        product_id = products["data"][0]["id"]
        concurrent = page.request.patch(
            f"{server.url}/api/v1/products/{product_id}?company_id={server.fixture.data.company_id}",
            headers={**headers, "If-Match": '"2"'},
            data={"uom": "CX"},
        )
        assert concurrent.status == 200
        page.get_by_label("Nome", exact=True).fill("Alteração obsoleta")
        page.get_by_role("button", name="Salvar alterações").click()
        expect(page.locator("#notice")).to_contain_text("Outra alteração foi salva")
        expect(page.locator("#detail-version")).to_have_text("Versão 2")
        page.get_by_role("button", name="Atualizar detalhe", exact=True).click()
        expect(page.locator("#detail-version")).to_have_text("Versão 3")
        expect(page.get_by_label("Nome", exact=True)).to_have_value("Caminhão de aventuras azul")
        page.get_by_label("Código de barras", exact=True).fill("7891234567895")
        page.get_by_role("button", name="Adicionar código").click()
        expect(page.locator("#detail-version")).to_have_text("Versão 4")
        expect(page.locator("#barcode-list")).to_contain_text("7891234567895")
        page.get_by_label("Código de barras", exact=True).fill("7891234567895")
        page.get_by_role("button", name="Adicionar código").click()
        expect(page.locator("#notice")).to_contain_text("já existe na empresa")
        expect(page.locator("#detail-version")).to_have_text("Versão 4")
        for version, action in (
            (5, "Enviar para homologação"),
            (6, "Ativar produto"),
            (7, "Descontinuar produto"),
        ):
            page.get_by_role("button", name=action, exact=True).click()
            expect(page.locator("#detail-version")).to_have_text(f"Versão {version}")
        expect(page.locator("[aria-current=step]")).to_have_text("Fora de linha")
        expect(page.locator("#transition-actions button")).to_have_count(0)
        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "product-detail-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(artifacts / "product-detail-mobile.png"), full_page=True)
        page.get_by_role("button", name="Voltar ao catálogo").click()
        expect(page.locator("#product-rows tr")).to_have_count(1)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.screenshot(path=str(artifacts / "product-list-desktop.png"), full_page=True)
        page.locator("#company").select_option(str(server.fixture.data.other_company_id))
        expect(page.locator("#empty")).to_be_visible()
        expect(page.locator("#product-rows tr")).to_have_count(0)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        page.get_by_role("button", name="Sair", exact=True).click()
        expect(page.get_by_label("Token de acesso")).to_have_value("")
        expect(page.locator("#catalog")).to_be_hidden()
        expect(page.locator("#product-rows tr")).to_have_count(0)
        expect(page.locator("#detail-title")).to_have_text("")
        assert failures == []
        browser.close()

        async def verify_effects() -> None:
            async with server.fixture.data.database.session() as session:
                events = (
                    await session.scalars(
                        select(OutboxEventModel).where(
                            OutboxEventModel.source_module == "product",
                            OutboxEventModel.aggregate_id.in_(
                                select(ProductModel.id).where(
                                    ProductModel.company_id == server.fixture.data.company_id
                                )
                            ),
                        )
                    )
                ).all()
                assert sorted(event.event_type for event in events) == sorted(
                    [
                        "ProductCreated",
                        "ProductUpdated",
                        "ProductUpdated",
                        "ProductBarcodeChanged",
                        "ProductUpdated",
                        "ProductActivated",
                        "ProductDiscontinued",
                    ]
                )
                audits = (
                    await session.scalars(
                        select(AuditEventModel).where(
                            AuditEventModel.company_id == server.fixture.data.company_id
                        )
                    )
                ).all()
                assert len(audits) == 7

        assert server.fixture.client.portal is not None
        server.fixture.client.portal.call(verify_effects)


def test_browser_read_only_identity_and_invalid_token() -> None:
    with browser_server(read_only=True) as server, sync_playwright() as playwright:

        async def seed() -> None:
            async with server.fixture.data.database.session() as session, session.begin():
                for index in range(21):
                    await ProductRepository(session, company_id=server.fixture.data.company_id).add(
                        server.fixture.data.product(code=f"READ-{index:02}"),
                        actor_id=server.fixture.data.actor_id,
                    )

        assert server.fixture.client.portal is not None
        server.fixture.client.portal.call(seed)
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill("invalid-token")
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.locator("#notice")).to_be_visible()
        expect(page.locator("#connection")).to_be_visible()
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.get_by_role("heading", name="Catálogo de produtos")).to_be_visible()
        expect(page.locator("#new-product")).to_be_hidden()
        page.locator("#company").select_option(str(server.fixture.data.company_id))
        expect(page.locator("#product-rows tr")).to_have_count(20)
        page.get_by_role("button", name="Próxima", exact=True).click()
        expect(page.locator("#product-rows tr")).to_have_count(1)
        expect(page.locator("#next")).to_be_disabled()
        page.get_by_role("button", name="Anterior", exact=True).click()
        expect(page.locator("#product-rows tr")).to_have_count(20)
        page.locator("#product-rows button").first.click()
        expect(page.locator("#detail-title")).to_have_text("Product fixture")
        expect(page.locator("#save-details")).to_be_disabled()
        expect(page.locator("#barcode-form")).to_be_hidden()
        expect(page.locator("#transition-actions button")).to_have_count(0)
        browser.close()
