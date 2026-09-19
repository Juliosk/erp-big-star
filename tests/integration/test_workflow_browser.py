"""Workflow Cockpit through Chromium, real HTTP, dev auth and PostgreSQL."""

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
from sqlalchemy import func, select

from erp.apps.api.app import create_app
from erp.modules.workflow.infrastructure import ApprovalDecisionModel, WorkflowInstanceModel
from erp.platform.config import Settings, get_settings
from erp.platform.config.settings import Environment
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_workflow_api import WorkflowApiFixture, workflow_api

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True)
class WorkflowBrowserServer:
    url: str
    token: str
    fixture: WorkflowApiFixture


@contextmanager
def workflow_browser_server() -> Iterator[WorkflowBrowserServer]:
    with workflow_api() as api, socket.socket() as listener:
        token = "workflow-browser-" + uuid4().hex
        values = get_settings().model_dump()
        values.update(
            environment=Environment.TEST,
            dev_auth_enabled=True,
            dev_auth_token=SecretStr(token),
            dev_auth_actor_id=api.data.actor_id,
            dev_auth_company_ids=(api.data.company_id, api.data.other_company_id),
        )
        settings = Settings.model_validate(values)
        database = Database(settings)
        application = create_app(settings, database)
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
                    raise RuntimeError("Workflow browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield WorkflowBrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}", token, api
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


def test_workflow_cockpit_definition_approval_history_and_company_isolation() -> None:
    with workflow_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        headers = {"Authorization": f"Bearer {server.token}"}

        definition = page.request.post(
            server.url + "/api/v1/workflow/definitions",
            headers=headers,
            data={
                "company_id": str(server.fixture.data.company_id),
                "code": "WF-WEB-APPROVAL",
                "name": "Aprovação web",
                "source_module": "SALES",
                "source_type": "QUOTE",
                "approval_mode": "SEQUENTIAL",
                "steps": [
                    {
                        "sequence": 1,
                        "code": "COMMERCIAL",
                        "name": "Alçada comercial",
                        "required_permission": "workflow.approval.decide",
                        "threshold_amount": "100.00",
                    }
                ],
            },
        )
        assert definition.ok
        source_id = uuid4()
        opened = page.request.post(
            server.url + "/api/v1/workflow/instances",
            headers=headers,
            data={
                "company_id": str(server.fixture.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(source_id),
                "source_fingerprint": "workflow-browser-e2e",
            },
        )
        assert opened.ok
        instance_id = opened.json()["instance"]["id"]

        page.goto(server.url + "/ui/")
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.locator("#workflow-nav")).to_be_visible()
        page.locator("#company").select_option(str(server.fixture.data.company_id))
        page.locator("#workflow-nav").click()
        expect(page.get_by_role("heading", name="Central de aprovações")).to_be_visible()
        expect(page.locator("#workflow-pending-count")).to_have_text("1")
        expect(page.locator("#workflow-approval-rows")).to_contain_text("Alçada comercial")
        expect(page.locator("#workflow-step-history")).to_contain_text("Em análise")

        page.locator("#workflow-comment").fill("Aprovado pelo cenário E2E Chromium.")
        page.get_by_role("button", name="Registrar decisão", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Aprovação registrada")
        expect(page.locator("#workflow-pending-count")).to_have_text("0")
        expect(page.locator("#workflow-empty")).to_be_visible()

        page.locator("#workflow-definition-code").fill("WF-WEB-CREATED")
        page.locator("#workflow-definition-name").fill("Definição criada no cockpit")
        page.locator("#workflow-source-module").fill("PURCHASING")
        page.locator("#workflow-source-type").fill("ORDER")
        page.locator("#workflow-step-name").fill("Alçada de compras")
        page.get_by_role("button", name="Criar definição", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Definição de workflow criada")
        expect(page.locator("#workflow-definition-rows")).to_contain_text("WF-WEB-CREATED")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(
            path=str(artifacts / "workflow-cockpit-desktop.png"), full_page=True
        )
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({
                tag: element.tagName,
                id: element.id,
                className: element.className,
                right: element.getBoundingClientRect().right
              }))"""
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), overflow
        page.screenshot(
            path=str(artifacts / "workflow-cockpit-mobile.png"), full_page=True
        )

        page.locator("#company").select_option(str(server.fixture.data.other_company_id))
        expect(page.locator("#workflow-empty")).to_be_visible()
        expect(page.locator("#workflow-approval-rows tr")).to_have_count(0)
        expect(page.locator("#workflow-definition-rows tr")).to_have_count(0)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()

        async def verify_effects() -> None:
            async with server.fixture.data.database.session() as session:
                instance = await session.scalar(
                    select(WorkflowInstanceModel).where(
                        WorkflowInstanceModel.id == instance_id,
                        WorkflowInstanceModel.company_id
                        == server.fixture.data.company_id,
                    )
                )
                decisions = await session.scalar(
                    select(func.count())
                    .select_from(ApprovalDecisionModel)
                    .where(ApprovalDecisionModel.workflow_instance_id == instance_id)
                )
                events = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.aggregate_id == instance_id,
                        OutboxEventModel.event_type == "WorkflowInstanceApproved",
                    )
                )
                assert instance is not None
                assert instance.status == "APPROVED"
                assert decisions == 1
                assert events == 1

        assert server.fixture.client.portal is not None
        server.fixture.client.portal.call(verify_effects)
