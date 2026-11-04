"""Cash Flow cockpit behavior through a real Chromium browser."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.domain import PermissionCode
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_cash_flow_api import (
    _headers,
    _projection_body,
    cash_flow_api,
)
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@dataclass(frozen=True, slots=True)
class CashFlowBrowserServer:
    url: str
    token: str
    fixture: ProcurementFixture
    projection_id: UUID


@contextmanager
def cash_flow_browser_server() -> Iterator[CashFlowBrowserServer]:
    with cash_flow_api() as (client, fixture, resolver), socket.socket() as listener:
        projection_id = uuid4()
        body = _projection_body(fixture.company_id, projection_id, uuid4())
        body["minimum_reserve"] = "999999.00"
        created = client.post(
            "/api/v1/finance/cash-flow/projections",
            headers=_headers(**{"Idempotency-Key": "cash-flow-browser-194"}),
            json=body,
        )
        assert created.status_code == 201, created.text
        assert resolver.context is not None
        resolver.context = replace(
            resolver.context,
            permissions=resolver.context.permissions
            | {PermissionCode("admin.company.read")},
        )
        settings = get_settings()
        application = create_app(
            settings=settings,
            database=Database(settings),
            security_context_resolver=resolver,
        )
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(application, log_config=None, log_level="warning")
        )
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
                    raise RuntimeError("Cash Flow browser test HTTP server failed to start.")
                time.sleep(0.02)
            yield CashFlowBrowserServer(
                url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token="cash-flow-test-token",
                fixture=fixture,
                projection_id=projection_id,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."


def test_cash_flow_cockpit_runway_alerts_scenario_and_mobile_layout() -> None:
    with cash_flow_browser_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        failures: list[str] = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        response = page.goto(server.url + "/ui/finance/cash-flow")
        assert response is not None
        assert response.ok
        page.get_by_label("Token de acesso").fill(server.token)
        page.get_by_role("button", name="Conectar", exact=True).click()

        expect(page.get_by_role("heading", name="Radar de caixa")).to_be_visible()
        expect(page.locator("#cash-flow-nav")).to_be_visible()
        expect(page.locator("#cash-flow-chart svg")).to_be_visible()
        expect(page.locator("#cash-flow-version")).to_have_text("ETag · v1")
        expect(page.locator("#cash-flow-alert-list")).to_contain_text(
            "Reserva de segurança"
        )
        expect(page.locator("#cash-flow-gap")).to_be_visible()

        page.get_by_role("button", name="Simular cenário", exact=True).click()
        expect(page.get_by_role("heading", name="Simular sensibilidade")).to_be_visible()
        page.get_by_label("Atraso dos recebíveis").fill("30")
        page.get_by_label("Variação de custos").fill("15")
        page.get_by_role("button", name="Calcular impacto", exact=True).click()
        expect(page.locator("#notice")).to_contain_text(
            "sem alterar a posição operacional"
        )
        expect(page.locator("#cash-flow-scenario-mark")).to_be_visible()
        expect(page.locator("#cash-flow-chart .scenario")).to_have_count(1)
        assert page.locator("#cash-flow-chart .scenario").get_attribute("d")
        page.get_by_role("button", name="Voltar ao operacional", exact=True).click()
        expect(page.locator("#cash-flow-scenario-mark")).to_be_hidden()

        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=str(artifacts / "cash-flow-cockpit-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.locator("body *").evaluate_all(
            """elements => elements
              .filter(element => {
                const style = getComputedStyle(element);
                return element.getBoundingClientRect().right > window.innerWidth + 1
                  && style.overflowX !== "auto";
              })
              .slice(0, 10)
              .map(element => ({tag: element.tagName, id: element.id, right: element.getBoundingClientRect().right}))"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), overflow
        expect(page.get_by_role("heading", name="Radar de caixa")).to_be_visible()
        page.screenshot(path=str(artifacts / "cash-flow-cockpit-mobile.png"), full_page=True)
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert failures == []
        browser.close()


def test_cash_flow_cockpit_assets_keep_the_clean_web_contract() -> None:
    html = Path("erp/apps/web/static/index.html").read_text(encoding="utf-8")
    script = Path("erp/apps/web/static/cash-flow.js").read_text(encoding="utf-8")
    mount = Path("erp/apps/web/mount.py").read_text(encoding="utf-8")
    assert "RUNWAY DE LIQUIDEZ" in html
    assert "LABORATÓRIO STATELESS" in html
    assert 'can("finance.cash_flow.read")' in script
    assert "finance/cash-flow/alerts" in script
    assert "CashFlowAlertModel" not in script
    assert '"finance/cash-flow"' in mount


def test_cash_flow_runbook_preserves_operational_governance_and_closure() -> None:
    content = Path("docs/cash-flow-runbook.md").read_text(encoding="utf-8")
    assert "Migration `0050`" in content
    assert "`finance.cash_flow.read`" in content
    assert "`finance.cash_flow.project`" in content
    assert "`finance.cash_flow.scenario`" in content
    assert "`CashFlowSourceGap(source=RECEIVABLES)`" in content
    assert '`If-Match: "N"`' in content
    assert "CashFlowLiquidityAlertTriggered" in content
    assert "CashFlowProjectionRecomposed" in content
    assert "SELECT FOR UPDATE SKIP LOCKED" in content
    assert "docker system prune -a --volumes" in content
    assert "Encerramento do ecossistema financeiro" in content
    assert "1.887" in content
    assert "91,87%" in content
    assert "0050 (head)" in content


__all__: list[str] = []
