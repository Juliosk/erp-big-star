"""Treasury cockpit rendering and interactions through a real Chromium browser."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.domain import PermissionCode
from erp.modules.finance.application import FINANCE_TREASURY_BATCH_APPROVE
from erp.modules.finance.infrastructure import PaymentBatchReviewModel
from erp.modules.workflow.application.decisions import CommandMetadata, DecideWorkflowInstance
from erp.modules.workflow.domain import ApprovalDecisionKind
from erp.modules.workflow.infrastructure import WorkflowRepository, apply_workflow_decision
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_treasury_api import (
    ResolverStub,
    _body,
    _cnab_240_return,
    _context,
    _create,
    treasury_api,
)
from tests.integration.test_treasury_repository import TreasuryFixture

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True, slots=True)
class TreasuryBrowserServer:
    url: str
    token: str
    fixture: TreasuryFixture
    batch_id: UUID
    batch_code: str
    client: TestClient
    resolver: ResolverStub


@contextmanager
def treasury_browser_server(*, seed_batch: bool = True) -> Iterator[TreasuryBrowserServer]:
    with treasury_api() as (client, fixture, resolver), socket.socket() as listener:
        if seed_batch:
            created = _create(client, fixture)
            assert created.status_code == 201, created.text
            batch_id = UUID(created.json()["batch"]["id"])
            batch_code = str(created.json()["batch"]["code"])
        else:
            batch_id = fixture.batch.id
            batch_code = fixture.batch.code
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
                    raise RuntimeError("Treasury browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield TreasuryBrowserServer(
                url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token="treasury-test-token",
                fixture=fixture,
                batch_id=batch_id,
                batch_code=batch_code,
                client=client,
                resolver=resolver,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before fixture cleanup."


async def _block_batch(server: TreasuryBrowserServer) -> None:
    data = server.fixture.matching.data
    now = datetime.now(UTC)
    async with data.database.session() as session, session.begin():
        session.add(
            PaymentBatchReviewModel(
                id=uuid4(),
                company_id=data.company_id,
                payment_batch_id=server.batch_id,
                status="BLOCKED",
                blocked=True,
                required_since=now,
                last_event_at=now,
                source_states={
                    "procurement:three_way_match_session:web": {
                        "blocked": True,
                        "status": "BLOCKED",
                    }
                },
                reasons=[
                    {
                        "event_type": "MatchingDiscrepancyDetected",
                        "aggregate_version": 7,
                        "reason": "Three-way matching reported an unresolved discrepancy.",
                    }
                ],
                revision=1,
            )
        )


async def _approve_payment_workflow(
    server: TreasuryBrowserServer,
    workflow_instance_id: UUID,
) -> None:
    data = server.fixture.matching.data
    async with data.database.session() as session, session.begin():
        workflows = WorkflowRepository(session, company_id=data.company_id)
        instance = await workflows.get_instance(workflow_instance_id)
        assert instance is not None
        steps = await workflows.list_step_instances(
            workflow_instance_id=workflow_instance_id
        )
        assert len(steps) == 1
        await apply_workflow_decision(
            session,
            DecideWorkflowInstance(
                company_id=data.company_id,
                workflow_instance_id=workflow_instance_id,
                step_instance_id=steps[0].id,
                expected_version=instance.version,
                decision=ApprovalDecisionKind.APPROVED,
                reason_code="PAYMENT_BATCH_APPROVED",
                comment="Aprovado por ator segregado no E2E Chromium de tesouraria.",
                metadata=CommandMetadata(uuid4(), uuid4()),
            ),
            actor_id=server.fixture.batch_approver,
            actor_permissions=frozenset({str(FINANCE_TREASURY_BATCH_APPROVE)}),
        )


def test_treasury_cockpit_dry_run_m22_queue_and_blocked_explanation() -> None:
    with treasury_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        response = page.goto(server.url + "/ui/treasury")
        assert response is not None
        assert response.ok
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        expect(page.get_by_role("heading", name="Sala de liquidação")).to_be_visible()
        expect(page.locator("#treasury-nav")).to_be_visible()
        expect(page.locator("#treasury-batch-list")).to_contain_text(server.batch_code)

        page.locator(f'#treasury-batch-list button[data-batch-id="{server.batch_id}"]').click()
        expect(page.locator("#treasury-selected-version")).to_have_text("ETag · v1")
        expect(page.locator("#treasury-item-rows")).to_contain_text("***7654")
        expect(page.locator("#treasury-stage-eligibility")).to_contain_text("Elegível")

        page.get_by_role("button", name="Simular remessa", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Simulação bancária concluída")
        expect(page.locator("#treasury-artifact")).to_contain_text("SIMULAÇÃO")
        expect(page.locator("#treasury-artifact-name")).to_contain_text("DRYRUN-")

        page.get_by_role("button", name="Solicitar alçada M22", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("encaminhado para a alçada M22")
        expect(page.locator("#treasury-stage-approval")).to_contain_text("Em análise")
        expect(page.locator("#treasury-workflow-id")).not_to_have_value("")

        assert server.client.portal is not None
        server.client.portal.call(_block_batch, server)
        page.get_by_role("button", name="Atualizar fila", exact=True).click()
        expect(page.locator("#treasury-review-title")).to_have_text("Bloqueado")
        expect(page.locator("#treasury-review-reasons")).to_contain_text(
            "Divergência do Three-Way Match ainda não resolvida."
        )
        expect(page.locator("#treasury-action-blocked")).to_be_visible()
        expect(page.locator("#treasury-remittance")).to_be_hidden()
        expect(page.locator("#treasury-blocked")).to_have_text("1")

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "treasury-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        page.screenshot(path=str(artifacts / "treasury-cockpit-mobile.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()


def test_treasury_browser_full_payment_journey_requires_bank_confirmation() -> None:
    with treasury_browser_server(seed_batch=False) as server, sync_playwright() as playwright:
        data = server.fixture.matching.data
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        response = page.goto(server.url + "/ui/treasury")
        assert response is not None
        assert response.ok
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()
        batch_code = f"E2E-{uuid4().hex[:10].upper()}"
        creation = page.evaluate(
            """async ({token, key, body}) => {
              const response = await fetch("/api/v1/finance/treasury/batches", {
                method: "POST",
                headers: {
                  Authorization: `Bearer ${token}`,
                  "Content-Type": "application/json",
                  "Idempotency-Key": key,
                },
                body: JSON.stringify(body),
              });
              return {
                status: response.status,
                etag: response.headers.get("ETag"),
                body: await response.json(),
              };
            }""",
            {
                "token": server.token,
                "key": str(uuid4()),
                "body": _body(server.fixture, code=batch_code),
            },
        )
        assert creation["status"] == 201
        assert creation["etag"] == '"1"'
        assert creation["body"]["batch"]["status"] == "DRAFT"
        batch_id = UUID(creation["body"]["batch"]["id"])
        cast(FastAPI, server.client.app).state.test_batch_id = str(batch_id)

        page.get_by_role("button", name="Atualizar fila", exact=True).click()
        expect(page.locator("#treasury-batch-list")).to_contain_text(batch_code)
        page.locator(
            f'#treasury-batch-list button[data-batch-id="{batch_id}"]'
        ).click()

        expect(page.locator("#treasury-stage-bank")).to_contain_text("Sem confirmação")
        page.get_by_role("button", name="Simular remessa", exact=True).click()
        expect(page.locator("#treasury-artifact-kind")).to_have_text("SIMULAÇÃO")
        expect(page.locator("#treasury-selected-version")).to_have_text("ETag · v1")

        page.get_by_role("button", name="Solicitar alçada M22", exact=True).click()
        expect(page.locator("#treasury-stage-approval")).to_contain_text("Em análise")
        workflow_id = UUID(page.locator("#treasury-workflow-id").input_value())
        assert server.fixture.batch_approver != data.actor_id
        assert server.fixture.batch_executor not in {
            data.actor_id,
            server.fixture.batch_approver,
        }
        assert server.client.portal is not None
        server.client.portal.call(_approve_payment_workflow, server, workflow_id)

        server.resolver.context = _context(server.fixture.batch_executor, data.company_id)
        page.get_by_role(
            "button", name="Validar aprovação e gerar remessa", exact=True
        ).click()
        expect(page.locator("#notice")).to_contain_text(
            "Remessa gerada e submetida com rastreabilidade transacional."
        )
        expect(page.locator("#treasury-artifact-kind")).to_have_text("REMESSA OFICIAL")
        expect(page.locator("#treasury-stage-remittance")).to_contain_text("Transmitida")
        expect(page.locator("#treasury-stage-bank")).to_contain_text("Sem confirmação")
        expect(page.locator("#treasury-selected-version")).to_have_text("ETag · v5")

        bank_return = _cnab_240_return(batch_id, server.fixture.batch.total_amount)
        settlement = page.evaluate(
            """async ({companyId, token, key, payload}) => {
              const response = await fetch(
                `/api/v1/finance/treasury/returns?company_id=${companyId}&remittance_format=CNAB_240`,
                {
                  method: "POST",
                  headers: {
                    Authorization: `Bearer ${token}`,
                    "Content-Type": "text/plain",
                    "Idempotency-Key": key,
                  },
                  body: payload,
                },
              );
              return {status: response.status, body: await response.json()};
            }""",
            {
                "companyId": str(data.company_id),
                "token": server.token,
                "key": str(uuid4()),
                "payload": bank_return.decode("ascii"),
            },
        )
        assert settlement["status"] == 200
        assert settlement["body"]["settlements"] == [
            {
                "payment_batch_id": str(batch_id),
                "status": "CONFIRMED",
                "version": 6,
                "replayed": False,
            }
        ]

        page.get_by_role("button", name="Atualizar fila", exact=True).click()
        expect(page.locator("#treasury-stage-bank")).to_contain_text("Liquidado")
        expect(page.locator("#treasury-selected-meta")).to_contain_text("Confirmado")
        expect(page.locator("#treasury-selected-version")).to_have_text("ETag · v6")
        expect(page.locator("#treasury-audit")).to_contain_text("Confirmado")
        expect(page.locator("#treasury-remittance")).to_be_hidden()
        assert failures == []
        browser.close()


def test_treasury_cockpit_assets_keep_the_clean_web_contract() -> None:
    html = Path("erp/apps/web/static/index.html").read_text(encoding="utf-8")
    script = Path("erp/apps/web/static/treasury.js").read_text(encoding="utf-8")
    mount = Path("erp/apps/web/mount.py").read_text(encoding="utf-8")
    assert "FILA EXPLICÁVEL" in html
    assert "Circuito de liberação bancária" in html
    assert 'can("finance.treasury.read")' in script
    assert "finance/treasury/batches" in script
    assert "PaymentBatchReviewModel" not in script
    assert 'path.rstrip("/") == "treasury"' in mount


__all__: list[str] = []
