"""Pricing Cockpit through Chromium, real HTTP, dev auth and PostgreSQL."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr
from sqlalchemy import func, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.pricing.application.permissions import (
    PRICING_PRICE_ACTIVATE,
    PRICING_PRICE_CREATE,
    PRICING_SIMULATE,
    PricingAuthorization,
)
from erp.modules.pricing.application.policies import (
    CreateMinimumMarginPolicy,
    PricingPolicyService,
    UpsertStandardCostSeed,
)
from erp.modules.pricing.infrastructure import PostgresPricingPolicies, PricingSnapshotModel
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from tests.integration.test_pricing_api import PricingApiFixture, pricing_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class PricingBrowserServer:
    url: str
    token: str
    fixture: PricingApiFixture


@contextmanager
def pricing_browser_server() -> Iterator[PricingBrowserServer]:
    with pricing_api() as fixture, socket.socket() as listener:
        token = "pricing-browser-" + uuid4().hex
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
                    raise RuntimeError("Pricing browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield PricingBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, fixture
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_pricing_cockpit_lists_versions_simulation_snapshots_and_scope() -> None:
    with pricing_browser_server() as server:

        async def seed_product_and_policy() -> str:
            product = server.fixture.data.product(code="PRICEWEB")
            async with server.fixture.data.database.session() as session, session.begin():
                await ProductRepository(
                    session, company_id=server.fixture.data.company_id
                ).add(product, actor_id=server.fixture.data.actor_id)
            context = SecurityContext(
                principal=AuthenticatedPrincipal(
                    server.fixture.data.actor_id,
                    uuid4(),
                    AuthenticationLevel.LEVEL_1,
                ),
                permissions=frozenset(
                    {PRICING_PRICE_CREATE, PRICING_PRICE_ACTIVATE, PRICING_SIMULATE}
                ),
                scopes=frozenset(
                    {
                        Scope(ScopeType.COMPANY, server.fixture.data.company_id),
                        Scope(ScopeType.COMPANY, server.fixture.data.other_company_id),
                    }
                ),
            )
            service = PricingPolicyService(
                PostgresPricingPolicies(server.fixture.data.database),
                PricingAuthorization(
                    CompanyAccessService(
                        PostgresCorporateDirectory(server.fixture.data.database)
                    )
                ),
            )
            await service.upsert_standard_cost_seed(
                context,
                UpsertStandardCostSeed(
                    company_id=server.fixture.data.company_id,
                    product_id=product.id,
                    cost_amount=Decimal("60.00"),
                ),
            )
            await service.create_minimum_margin_policy(
                context,
                CreateMinimumMarginPolicy(
                    company_id=server.fixture.data.company_id,
                    code="web",
                    name="Web Pricing Margin",
                    minimum_margin=Decimal("0.3000"),
                ),
            )
            return str(product.id)

        assert server.fixture.client.portal is not None
        product_id = server.fixture.client.portal.call(seed_product_and_policy)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            failures: list[str] = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(server.url + "/ui/")
            page.get_by_label("Token de acesso").fill(server.token)
            page.get_by_role("button", name="Conectar", exact=True).click()
            expect(page.get_by_role("heading", name="Catálogo de produtos")).to_be_visible()
            expect(page.locator("#pricing-nav")).to_be_visible()
            page.locator("#company").select_option(str(server.fixture.data.company_id))
            page.locator("#pricing-nav").click()
            expect(page.get_by_role("heading", name="Pricing Cockpit")).to_be_visible()
            expect(page.locator("#pricing-empty")).to_be_visible()

            page.locator("#pricing-code").fill("WEB-PRI")
            page.locator("#pricing-name").fill("Tabela Web Pricing")
            page.locator("#pricing-type").select_option("BASE")
            page.get_by_role("button", name="Criar lista", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Lista de preço criada")
            expect(page.locator("#pricing-list-rows")).to_contain_text("WEB-PRI")
            expect(page.locator("#pricing-selected-title")).to_have_text("Tabela Web Pricing")

            page.locator("#pricing-valid-from").fill("2026-09-13")
            page.locator("#pricing-version-product-id").fill(product_id)
            page.locator("#pricing-price-amount").fill("100.00")
            page.locator("#pricing-minimum-price").fill("90.00")
            page.locator("#pricing-target-margin").fill("0.4000")
            page.get_by_role("button", name="Criar versão", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Versão de lista criada")
            expect(page.locator("#pricing-version-rows")).to_contain_text("DRAFT")

            page.get_by_role("button", name="Ativar", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Versão de lista ativada")
            expect(page.locator("#pricing-version-rows")).to_contain_text("ACTIVE")

            page.locator("#pricing-simulation-product-id").fill(product_id)
            page.locator("#pricing-simulation-quantity").fill("2")
            page.locator("#pricing-proposed-price").fill("130.00")
            page.get_by_role("button", name="Simular sem gravar", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("sem persistir snapshot")
            expect(page.locator("#pricing-decision")).to_contain_text("não persistido")
            expect(page.locator("#pricing-decision")).to_contain_text("R$ 260,00")
            expect(page.locator("#pricing-snapshots-empty")).to_be_visible()

            page.get_by_role("button", name="Resolver e congelar", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("snapshot persistido")
            expect(page.locator("#pricing-decision")).not_to_contain_text("não persistido")
            expect(page.locator("#pricing-snapshot-rows")).to_contain_text("LEGACY_OPENING")
            expect(page.locator("#pricing-snapshot-rows")).to_contain_text("R$ 100,00")

            artifacts = Path("test-results")
            artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts / "pricing-cockpit-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(artifacts / "pricing-cockpit-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})

            page.locator("#company").select_option(str(server.fixture.data.other_company_id))
            expect(page.locator("#pricing-empty")).to_be_visible()
            expect(page.locator("#pricing-list-rows tr")).to_have_count(0)
            expect(page.locator("#pricing-snapshots-empty")).to_be_visible()
            expect(page.locator("#pricing-snapshot-rows tr")).to_have_count(0)
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            assert failures == []
            browser.close()

        async def count_snapshots() -> int:
            async with server.fixture.data.database.session() as session:
                return int(
                    await session.scalar(
                        select(func.count()).select_from(PricingSnapshotModel).where(
                            PricingSnapshotModel.company_id == server.fixture.data.company_id
                        )
                    )
                    or 0
                )

        assert server.fixture.client.portal.call(count_snapshots) == 1
