"""Three-way matching cockpit E2E through Chromium and real PostgreSQL."""

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
from sqlalchemy import delete, select, update

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import PermissionCode
from erp.modules.fiscal.infrastructure import InboundFiscalDocumentItemModel
from erp.modules.procurement.infrastructure import MatchingSessionModel
from erp.modules.workflow.application import WORKFLOW_APPROVAL_DECIDE
from erp.modules.workflow.domain import (
    ApprovalMode,
    WorkflowDefinition,
    WorkflowStepDefinition,
)
from erp.modules.workflow.infrastructure import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowRepository,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_matching_api import MatchingApiFixture, matching_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


class BrowserResolver:
    def __init__(self, contexts: dict[str, SecurityContext]) -> None:
        self.contexts = contexts

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.contexts.get(access_token)


@dataclass(frozen=True)
class MatchingBrowserServer:
    url: str
    token: str
    api: MatchingApiFixture
    resolver: BrowserResolver
    approver: SecurityContext


async def _prepare_browser_data(api: MatchingApiFixture) -> None:
    fixture = api.fixture
    fiscal_item_id = fixture.aggregate.lines[0].fiscal_document_item_id
    async with fixture.data.database.session() as session, session.begin():
        await session.execute(
            update(InboundFiscalDocumentItemModel)
            .where(InboundFiscalDocumentItemModel.id == fiscal_item_id)
            .values(unit_price="99.00", total_amount="990.00")
        )
        repository = WorkflowRepository(session, company_id=fixture.data.company_id)
        definition = WorkflowDefinition.create(
            company_id=fixture.data.company_id,
            code="MATCHING-OVERRIDE",
            name="Alçada E2E de exceção do matching",
            source_module="PROCUREMENT",
            source_type="MATCHING_OVERRIDE",
            approval_mode=ApprovalMode.SEQUENTIAL,
        )
        step = WorkflowStepDefinition.create(
            company_id=fixture.data.company_id,
            sequence=1,
            code="FINANCE_MANAGER",
            name="Gestor financeiro",
            required_permission=str(WORKFLOW_APPROVAL_DECIDE),
            threshold_amount=None,
        )
        await repository.add_definition(definition, steps=(step,), actor_id=fixture.data.actor_id)


async def _cleanup_browser_data(api: MatchingApiFixture) -> None:
    company_id = api.fixture.data.company_id
    async with api.fixture.data.database.session() as session, session.begin():
        await session.execute(
            delete(OutboxEventModel).where(
                (
                    (OutboxEventModel.source_module == "workflow")
                    & OutboxEventModel.aggregate_id.in_(
                        select(WorkflowInstanceModel.id).where(
                            WorkflowInstanceModel.company_id == company_id
                        )
                    )
                )
                | (
                    (OutboxEventModel.source_module == "procurement")
                    & OutboxEventModel.aggregate_id.in_(
                        select(MatchingSessionModel.id).where(
                            MatchingSessionModel.company_id == company_id
                        )
                    )
                )
            )
        )
        await session.execute(
            delete(AuditEventModel).where(
                AuditEventModel.company_id == company_id,
                AuditEventModel.module.in_(("procurement", "workflow")),
            )
        )
        await session.execute(
            delete(IdempotencyRecordModel).where(
                IdempotencyRecordModel.scope.like(f"procurement-matching-governance:{company_id}:%")
            )
        )
        await session.execute(
            delete(ApprovalDecisionModel).where(ApprovalDecisionModel.company_id == company_id)
        )
        await session.execute(
            delete(WorkflowStepInstanceModel).where(
                WorkflowStepInstanceModel.company_id == company_id
            )
        )
        await session.execute(
            delete(WorkflowInstanceModel).where(WorkflowInstanceModel.company_id == company_id)
        )
        await session.execute(
            delete(WorkflowStepDefinitionModel).where(
                WorkflowStepDefinitionModel.company_id == company_id
            )
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(WorkflowDefinitionModel.company_id == company_id)
        )


@contextmanager
def matching_browser_server() -> Iterator[MatchingBrowserServer]:
    with matching_api() as api, socket.socket() as listener:
        assert api.resolver.context is not None
        assert api.client.portal is not None
        api.client.portal.call(_prepare_browser_data, api)
        token = "matching-browser-operator"
        permissions = api.resolver.context.permissions | {
            PermissionCode("admin.company.read"),
            PermissionCode("workflow.request.create"),
            PermissionCode("workflow.approval.decide"),
        }
        buyer = replace(api.resolver.context, permissions=frozenset(permissions))
        approver = replace(
            buyer,
            principal=replace(buyer.principal, user_id=uuid4()),
        )
        resolver = BrowserResolver({token: buyer})
        application = create_app(
            settings=get_settings(),
            database=Database(get_settings()),
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
                    raise RuntimeError("Matching browser server failed to start.")
                time.sleep(0.02)
            yield MatchingBrowserServer(
                url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token=token,
                api=api,
                resolver=resolver,
                approver=approver,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."
            api.client.portal.call(_cleanup_browser_data, api)


def test_matching_cockpit_creation_discrepancy_override_desktop_and_mobile() -> None:
    with matching_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        fixture = server.api.fixture
        aggregate = fixture.aggregate
        line = aggregate.lines[0]

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.locator("#company").select_option(str(fixture.data.company_id))
        expect(page.locator("#procurement-nav")).to_be_visible()
        page.locator("#procurement-nav").click()
        expect(page.get_by_role("heading", name="Three-Way Match")).to_be_visible()

        page.get_by_text("Nova sessão de conferência", exact=True).click()
        purchase = aggregate.purchase_order_snapshot.purchase_order
        receiving = aggregate.receiving_fiscal_snapshot
        financial = aggregate.financial_snapshot
        page.locator("#matching-purchase-order-id").fill(str(purchase.id))
        page.locator("#matching-goods-receipt-id").fill(str(receiving.goods_receipts[0].id))
        page.locator("#matching-inbound-document-id").fill(str(receiving.fiscal_documents[0].id))
        page.locator("#matching-provisional-entry-id").fill(str(financial.provisional_entry.id))
        page.locator("#matching-purchase-item-id").fill(str(line.purchase_order_item_id))
        page.locator("#matching-receipt-item-id").fill(str(line.goods_receipt_item_id))
        page.locator("#matching-fiscal-item-id").fill(str(line.fiscal_document_item_id))
        page.locator("#matching-match-key").fill(line.match_key)
        page.get_by_role("button", name="Criar sessão", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("snapshot imutável")
        expect(page.locator("#matching-dossier-status")).to_contain_text("Pendente")

        page.get_by_role("button", name="Executar conferência", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("divergências explicáveis")
        expect(page.locator("#matching-dossier-status")).to_contain_text("Divergência detectada")
        expect(page.locator("#matching-line-cards")).to_contain_text("Preço divergente")
        expect(page.locator("#matching-line-cards")).to_contain_text(
            "Preço unitário fora da tolerância"
        )

        page.locator("#matching-override-justification").fill(
            "Diferença comercial documentada e submetida à governança financeira."
        )
        page.get_by_role("button", name="Solicitar alçada M22", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("encaminhado para a alçada M22")
        expect(page.locator("#matching-workflow-card")).to_contain_text("Gestor financeiro")

        # The same browser session keeps the workflow dossier while the resolver now
        # represents a distinct approver, proving the SoD boundary on the server.
        server.resolver.contexts[server.token] = server.approver
        page.get_by_role("button", name="Aprovar override", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Decisão de alçada registrada")
        expect(page.locator("#matching-dossier-status")).to_contain_text("Override aprovado")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "matching-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "matching-cockpit-mobile.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()


def test_matching_cockpit_assets_expose_governance_contract() -> None:
    html = Path("erp/apps/web/static/index.html").read_text(encoding="utf-8")
    script = Path("erp/apps/web/static/matching.js").read_text(encoding="utf-8")
    assert "M6 · M11 · M12" in html
    assert "FILA EXPLICÁVEL" in html
    assert "procurement.matching.read" in script
    assert "workflow.approval.decide" in script
    assert "/override/decide" in script
