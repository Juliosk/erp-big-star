"""Treasury cockpit rendering and interactions through a real Chromium browser."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.domain import PermissionCode
from erp.modules.finance.infrastructure import PaymentBatchReviewModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_treasury_api import _create, treasury_api
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


@contextmanager
def treasury_browser_server() -> Iterator[TreasuryBrowserServer]:
    with treasury_api() as (client, fixture, resolver), socket.socket() as listener:
        created = _create(client, fixture)
        assert created.status_code == 201, created.text
        batch_id = UUID(created.json()["batch"]["id"])
        batch_code = str(created.json()["batch"]["code"])
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
