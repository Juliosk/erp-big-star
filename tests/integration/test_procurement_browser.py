"""M6 Procurement Cockpit E2E through Chromium and real PostgreSQL."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import delete, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import PermissionCode, Scope, ScopeType
from erp.modules.procurement.infrastructure import ProcurementApprovalDecisionConsumer
from erp.modules.workflow.infrastructure import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_procurement_purchasing_api import (
    PurchasingApiFixture,
    purchasing_api,
)
from tests.integration.test_procurement_supplier_repository import _cnpj

pytestmark = [pytest.mark.integration, pytest.mark.browser]


class BrowserResolver:
    def __init__(self, contexts: dict[str, SecurityContext]) -> None:
        self.contexts = contexts

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.contexts.get(access_token)


@dataclass(frozen=True)
class ProcurementBrowserServer:
    url: str
    buyer_token: str
    approver_token: str
    fixture: PurchasingApiFixture


async def _cleanup_workflow(fixture: PurchasingApiFixture) -> None:
    company_ids = (fixture.data.company_id, fixture.data.other_company_id)
    async with fixture.data.database.session() as session, session.begin():
        await session.execute(
            delete(OutboxEventModel).where(OutboxEventModel.source_module == "workflow")
        )
        await session.execute(
            delete(AuditEventModel).where(
                AuditEventModel.module == "workflow",
                AuditEventModel.company_id.in_(company_ids),
            )
        )
        await session.execute(
            delete(ApprovalDecisionModel).where(ApprovalDecisionModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(WorkflowStepInstanceModel).where(
                WorkflowStepInstanceModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowInstanceModel).where(WorkflowInstanceModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(WorkflowStepDefinitionModel).where(
                WorkflowStepDefinitionModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(
                WorkflowDefinitionModel.company_id.in_(company_ids)
            )
        )


@contextmanager
def procurement_browser_server() -> Iterator[ProcurementBrowserServer]:
    with purchasing_api() as fixture, socket.socket() as listener:
        assert fixture.resolver.context is not None
        buyer_token = "procurement-browser-buyer"
        approver_token = "procurement-browser-approver"
        scopes = frozenset(
            {
                Scope(ScopeType.COMPANY, fixture.data.company_id),
                Scope(ScopeType.COMPANY, fixture.data.other_company_id),
            }
        )
        common_permissions = fixture.resolver.context.permissions | {
            PermissionCode("admin.company.read"),
            PermissionCode("workflow.request.read"),
            PermissionCode("workflow.request.create"),
            PermissionCode("workflow.definition.manage"),
            PermissionCode("procurement.supplier.read"),
            PermissionCode("procurement.supplier.manage"),
            PermissionCode("procurement.requisition.read"),
            PermissionCode("procurement.requisition.manage"),
            PermissionCode("procurement.order.read"),
            PermissionCode("procurement.order.manage"),
        }
        buyer = replace(
            fixture.resolver.context,
            permissions=frozenset(common_permissions),
            scopes=scopes,
        )
        approver = replace(
            buyer,
            principal=replace(buyer.principal, user_id=uuid4()),
            permissions=frozenset(
                common_permissions | {PermissionCode("workflow.approval.decide")}
            ),
        )
        application = create_app(
            settings=get_settings(),
            database=Database(get_settings()),
            security_context_resolver=BrowserResolver(
                {buyer_token: buyer, approver_token: approver}
            ),
        )
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Procurement browser server failed to start.")
                time.sleep(0.02)
            yield ProcurementBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}",
                buyer_token,
                approver_token,
                fixture,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."
            assert fixture.client.portal is not None
            fixture.client.portal.call(_cleanup_workflow, fixture)


def test_procurement_cockpit_supplier_requisition_order_and_m22_decision() -> None:
    with procurement_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        buyer_headers = {"Authorization": f"Bearer {server.buyer_token}"}
        approver_headers = {"Authorization": f"Bearer {server.approver_token}"}
        company_id = server.fixture.data.company_id

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.buyer_token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.locator("#company").select_option(str(company_id))
        expect(page.locator("#procurement-nav")).to_be_visible()
        page.locator("#procurement-nav").click()
        expect(page.get_by_role("heading", name="Cockpit de compras")).to_be_visible()

        page.locator("#procurement-supplier-name").fill("Fornecedor E2E M6")
        page.locator("#procurement-supplier-trade-name").fill("Origem Segura")
        page.locator("#procurement-supplier-document").fill(_cnpj())
        page.get_by_role("button", name="Cadastrar fornecedor", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Fornecedor cadastrado")
        expect(page.locator("#procurement-supplier-rows")).to_contain_text("Fornecedor E2E M6")

        page.locator("#procurement-requisition-number").fill("RC-E2E-0139")
        page.locator("#procurement-cost-center").fill(str(uuid4()))
        page.locator("#procurement-product-id").fill(str(server.fixture.product_id))
        page.locator("#procurement-quantity").fill("4")
        page.locator("#procurement-needed-by").fill(
            (datetime.now(UTC).date() + timedelta(days=7)).isoformat()
        )
        page.locator("#procurement-urgency").select_option("HIGH")
        page.locator("#procurement-specification").fill("Reposição de produto homologado")
        page.locator("#procurement-justification").fill("Cobertura do plano comercial")
        page.get_by_role("button", name="Abrir requisição", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Requisição de compra aberta")
        requisition_row = page.locator("#procurement-requisition-rows tr", has_text="RC-E2E-0139")
        requisition_row.get_by_role("button", name="Enviar para aprovação").click()
        expect(page.locator("#notice")).to_contain_text("Requisição enviada para aprovação")

        requisitions = page.request.get(
            server.url + f"/api/v1/procurement/requisitions?company_id={company_id}",
            headers=buyer_headers,
        ).json()["data"]
        requisition = next(item for item in requisitions if item["number"] == "RC-E2E-0139")
        approved_requisition = page.request.post(
            server.url
            + f"/api/v1/procurement/requisitions/{requisition['id']}/approve?company_id={company_id}",
            headers={**approver_headers, "If-Match": f'"{requisition["version"]}"'},
        )
        assert approved_requisition.ok
        page.locator("#procurement-refresh").click()
        expect(requisition_row).to_contain_text("Aprovado")

        page.locator("#procurement-order-number").fill("PC-E2E-0139")
        page.locator("#procurement-order-requisition").select_option(requisition["id"])
        page.locator("#procurement-order-supplier").select_option(label="Fornecedor E2E M6")
        page.locator("#procurement-order-unit-price").fill("27.50")
        page.get_by_role("button", name="Criar pedido", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Pedido de compra criado")
        order_row = page.locator("#procurement-order-rows tr", has_text="PC-E2E-0139")
        order_row.get_by_role("button", name="Solicitar aprovação M22").click()
        expect(page.locator("#notice")).to_contain_text("Aprovação formal solicitada ao M22")

        order = next(
            item
            for item in page.request.get(
                server.url + f"/api/v1/procurement/purchase-orders?company_id={company_id}",
                headers=buyer_headers,
            ).json()["data"]
            if item["number"] == "PC-E2E-0139"
        )
        definition = page.request.post(
            server.url + "/api/v1/workflow/definitions",
            headers=buyer_headers,
            data={
                "company_id": str(company_id),
                "code": "M6-PO-E2E",
                "name": "Alçada de pedido de compra",
                "source_module": "PROCUREMENT",
                "source_type": "PURCHASE_ORDER",
                "approval_mode": "SEQUENTIAL",
                "steps": [
                    {
                        "sequence": 1,
                        "code": "PURCHASING_MANAGER",
                        "name": "Gerência de compras",
                        "required_permission": "workflow.approval.decide",
                        "threshold_amount": "1.00",
                    }
                ],
            },
        )
        assert definition.ok
        opened = page.request.post(
            server.url + "/api/v1/workflow/instances",
            headers=buyer_headers,
            data={
                "company_id": str(company_id),
                "source_module": "PROCUREMENT",
                "source_type": "PURCHASE_ORDER",
                "source_id": order["id"],
                "source_fingerprint": f"purchase-order:{order['id']}:v{order['version']}",
            },
        )
        assert opened.ok

        page.get_by_role("button", name="Sair", exact=True).click()
        page.get_by_label("Token de acesso").fill(server.approver_token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.locator("#company").select_option(str(company_id))
        page.locator("#workflow-nav").click()
        expect(page.locator("#workflow-approval-rows")).to_contain_text("Gerência de compras")
        page.locator("#workflow-comment").fill("Alçada validada no E2E do M6.")
        page.get_by_role("button", name="Registrar decisão", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Aprovação registrada")

        async def consume_decision() -> None:
            async with server.fixture.data.database.session() as session:
                event = await session.scalar(
                    select(OutboxEventModel)
                    .where(OutboxEventModel.event_type == "ApprovalDecisionMade")
                    .order_by(OutboxEventModel.occurred_at.desc())
                    .limit(1)
                )
                assert event is not None
                envelope = MessageEnvelope.model_validate(event.payload)
            result = await ProcurementApprovalDecisionConsumer(
                server.fixture.data.database
            ).consume(envelope)
            assert result.processed

        assert server.fixture.client.portal is not None
        server.fixture.client.portal.call(consume_decision)

        page.get_by_role("button", name="Sair", exact=True).click()
        page.get_by_label("Token de acesso").fill(server.buyer_token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        page.locator("#company").select_option(str(company_id))
        page.locator("#procurement-nav").click()
        expect(page.locator("#procurement-order-rows tr", has_text="PC-E2E-0139")).to_contain_text(
            "Aprovado"
        )

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "procurement-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "procurement-cockpit-mobile.png"), full_page=True)
        page.locator("#company").select_option(str(server.fixture.data.other_company_id))
        expect(page.locator("#procurement-supplier-empty")).to_be_visible()
        expect(page.locator("#procurement-requisition-empty")).to_be_visible()
        expect(page.locator("#procurement-order-empty")).to_be_visible()
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()
