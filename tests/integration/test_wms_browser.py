"""WMS Cockpit through Chromium, real HTTP, dev auth and PostgreSQL."""

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
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.wms.infrastructure import PackageItemModel, PackageModel
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from tests.integration.test_wms_api import WmsApiFixture, wms_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class WmsBrowserServer:
    url: str
    token: str
    fixture: WmsApiFixture


@contextmanager
def wms_browser_server() -> Iterator[WmsBrowserServer]:
    with wms_api() as fixture, socket.socket() as listener:
        token = "wms-browser-" + uuid4().hex
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
                    raise RuntimeError("WMS browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield WmsBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, fixture
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_wms_cockpit_wave_scan_package_and_company_isolation() -> None:
    with wms_browser_server() as server:

        async def seed_product() -> str:
            product = server.fixture.data.product(code="WMSWEB")
            async with server.fixture.data.database.session() as session, session.begin():
                await ProductRepository(
                    session, company_id=server.fixture.data.company_id
                ).add(product, actor_id=server.fixture.data.actor_id)
                session.add(
                    ProductBarcodeModel(
                        id=uuid4(),
                        company_id=server.fixture.data.company_id,
                        product_id=product.id,
                        barcode_type="EAN",
                        barcode="WMSWEB001",
                        created_by=server.fixture.data.actor_id,
                        updated_by=server.fixture.data.actor_id,
                    )
                )
            return str(product.id)

        assert server.fixture.client.portal is not None
        product_id = server.fixture.client.portal.call(seed_product)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            failures: list[str] = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(server.url + "/ui/")
            page.get_by_label("Token de acesso").fill(server.token)
            page.get_by_role("button", name="Conectar", exact=True).click()
            expect(page.get_by_role("heading", name="Catálogo de produtos")).to_be_visible()
            expect(page.locator("#wms-nav")).to_be_visible()
            page.locator("#company").select_option(str(server.fixture.data.company_id))
            page.locator("#wms-nav").click()
            expect(page.get_by_role("heading", name="Cockpit de expedição")).to_be_visible()
            expect(page.locator("#wms-empty")).to_be_visible()

            page.locator("#wms-wave-code").fill("WMS-WEB")
            page.locator("#wms-product-id").fill(product_id)
            page.locator("#wms-wave-quantity").fill("1")
            page.get_by_role("button", name="Criar onda", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Onda de separação criada")
            expect(page.locator("#wms-wave-rows")).to_contain_text("WMS-WEB")
            expect(page.locator("#wms-task-rows")).to_contain_text("0.000000 / 1.000000")

            page.get_by_role("button", name="Liberar", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Onda liberada")
            expect(page.locator("#wms-selected-meta")).to_contain_text("RELEASED")

            page.locator("#wms-scan-barcode").fill("WMSWEB001")
            page.locator("#wms-scan-quantity").fill("1")
            page.get_by_role("button", name="Bipar tarefa", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Tarefa bipada")
            expect(page.locator("#wms-task-rows")).to_contain_text("1.000000 / 1.000000")
            expect(page.locator("#wms-task-rows")).to_contain_text("COMPLETED")

            page.locator("#wms-package-code").fill("PKG-WEB")
            page.locator("#wms-package-weight").fill("300")
            page.get_by_role("button", name="Criar pacote", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Pacote criado")
            expect(page.locator("#wms-package-card")).to_contain_text("PKG-WEB")
            expect(page.locator("#wms-package-card")).to_contain_text("DRAFT")

            page.locator("#wms-package-quantity").fill("1")
            page.get_by_role("button", name="Adicionar item", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Item adicionado")
            expect(page.locator("#wms-package-card")).to_contain_text("1 item(ns)")

            page.get_by_role("button", name="Verificar pacote", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Pacote verificado")
            expect(page.locator("#wms-package-card")).to_contain_text("VERIFIED")

            page.get_by_role("button", name="Finalizar pacote", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Pacote finalizado")
            expect(page.locator("#wms-package-card")).to_contain_text("FINALIZED")

            artifacts = Path("test-results")
            artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts / "wms-cockpit-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(artifacts / "wms-cockpit-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})

            page.locator("#company").select_option(str(server.fixture.data.other_company_id))
            expect(page.locator("#wms-empty")).to_be_visible()
            expect(page.locator("#wms-wave-rows tr")).to_have_count(0)
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            assert failures == []
            browser.close()

        async def verify_package() -> None:
            async with server.fixture.data.database.session() as session:
                package = await session.scalar(
                    select(PackageModel).where(
                        PackageModel.company_id == server.fixture.data.company_id,
                        PackageModel.package_code == "PKG-WEB",
                    )
                )
                item = await session.scalar(
                    select(PackageItemModel).where(
                        PackageItemModel.company_id == server.fixture.data.company_id,
                        PackageItemModel.product_id == UUID(product_id),
                    )
                )
                assert package is not None
                assert package.status == "FINALIZED"
                assert package.version == 3
                assert item is not None
                assert f"{item.quantity:.6f}" == "1.000000"

        server.fixture.client.portal.call(verify_package)
