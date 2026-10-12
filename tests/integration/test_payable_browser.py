"""M12 Payable Cockpit E2E through Chromium, real HTTP and PostgreSQL."""

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
from sqlalchemy import delete

from erp.apps.api.app import create_app
from erp.modules.workflow.infrastructure.workflow_model import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_payable_api import payable_api
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class PayableBrowserServer:
    url: str
    token: str
    data: ProcurementFixture


async def _cleanup_workflow(data: ProcurementFixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
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
def payable_browser_server() -> Iterator[PayableBrowserServer]:
    with payable_api() as (client, data, _), socket.socket() as listener:
        token = "payable-browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=data.actor_id,
            dev_auth_company_ids=(data.company_id, data.other_company_id),
            dev_auth_permissions=(
                "admin.company.read",
                "product.product.read",
                "finance.payable.read",
                "finance.payable.create",
                "finance.payable.approve",
                "finance.payable.adjust",
                "workflow.definition.manage",
            ),
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
                    raise RuntimeError("Payable browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield PayableBrowserServer(f"http://127.0.0.1:{listener.getsockname()[1]}", token, data)
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."
            assert client.portal is not None
            client.portal.call(_cleanup_workflow, data)


def test_payable_cockpit_adjustment_and_governance_flow() -> None:
    with payable_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        headers = {
            "Authorization": f"Bearer {server.token}",
            "Idempotency-Key": str(uuid4()),
        }
        definition = page.request.post(
            server.url + "/api/v1/workflow/definitions",
            headers=headers,
            data={
                "company_id": str(server.data.company_id),
                "code": "PAYABLE-WEB-0162",
                "name": "Alçada financeira web",
                "source_module": "FINANCE",
                "source_type": "PAYABLE",
                "approval_mode": "SEQUENTIAL",
                "steps": [
                    {
                        "sequence": 1,
                        "code": "FINANCE_MANAGER",
                        "name": "Gerência financeira",
                        "required_permission": "finance.payable.approve",
                        "threshold_amount": "100.00",
                    }
                ],
            },
        )
        assert definition.ok, definition.text()
        created = page.request.post(
            server.url + "/api/v1/finance/payables",
            headers=headers,
            data={
                "company_id": str(server.data.company_id),
                "number": "AP-WEB-0162",
                "supplier_id": str(uuid4()),
                "supplier_tax_id": "12345678000195",
                "currency": "BRL",
                "nominal_amount": "100.00",
                "installments": [
                    {"due_date": "2026-11-10", "amount": "40.00"},
                    {"due_date": "2026-12-10", "amount": "60.00"},
                ],
            },
        )
        assert created.ok, created.text()

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.locator("#finance-nav")).to_be_visible()
        page.locator("#company").select_option(str(server.data.company_id))
        page.locator("#finance-nav").click()
        expect(page.get_by_role("heading", name="Cockpit de contas a pagar")).to_be_visible()
        expect(page.locator("#finance-payable-rows")).to_contain_text("AP-WEB-0162")
        expect(page.locator("#finance-count")).to_have_text("1")

        row = page.locator("#finance-payable-rows tr", has_text="AP-WEB-0162")
        row.get_by_role("button", name="Analisar título AP-WEB-0162").click()
        expect(page.locator("#finance-selected-version")).to_have_text("ETag · v1")
        expect(page.locator("#finance-gate-approval")).to_contain_text("Não solicitada")

        page.locator("#finance-discount").fill("5.00")
        page.locator("#finance-surcharge").fill("10.00")
        page.get_by_role("button", name="Aplicar ajustes", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Ajustes financeiros aplicados")
        expect(page.locator("#finance-selected-version")).to_have_text("ETag · v2")
        expect(page.locator("#finance-total")).to_have_text("R$ 105,00")

        page.get_by_role("button", name="Submeter para aprovação", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("governança de alçada")
        expect(page.locator("#finance-selected-meta")).to_contain_text("Pendente de aprovação")
        expect(page.locator("#finance-gate-approval")).to_contain_text("Pendente M22")
        expect(page.locator("#finance-governance-alert")).to_contain_text("segregação de funções")

        output = Path("test-results/payable-cockpit-0162.png")
        output.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("heading", name="Cockpit de contas a pagar")).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path="test-results/payable-cockpit-0162-mobile.png", full_page=True)
        assert not failures
        browser.close()


def test_payable_cockpit_navigation_requires_read_permission() -> None:
    index = Path("erp/apps/web/static/app.js").read_text(encoding="utf-8")
    assert '$("finance-nav").hidden = !permissions.has("finance.payable.read")' in index
    module = Path("erp/apps/web/static/finance.js").read_text(encoding="utf-8")
    assert 'if (!can("finance.payable.read")) return;' in module
    assert "company_id=${context().company}" in module
