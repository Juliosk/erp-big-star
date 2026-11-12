"""Commit 220 REST, RBAC and Chromium coverage for the three governance tracks."""

import asyncio
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

from erp.apps.api.app import create_app
from erp.modules.admin.application import (
    ADMIN_COMPANY_READ,
    ListCompaniesService,
    SecurityContext,
)
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Company,
    CorporateStatus,
    PermissionCode,
    Scope,
    ScopeType,
    TenantContext,
)
from erp.modules.finance.application import (
    FINANCE_TREASURY_READ,
    FinanceAuthorization,
    FinanceCockpitPayment,
    FinanceCockpitService,
    FinanceCockpitSnapshot,
)
from erp.modules.finance.infrastructure import (
    PaymentRequestRepository,
    PostgresFinanceCockpitReader,
)
from erp.modules.fiscal.application import (
    FISCAL_TAX_RULE_READ,
    FiscalAuthorization,
    FiscalCockpitRule,
    FiscalCockpitService,
    FiscalCockpitSnapshot,
)
from erp.modules.fiscal.infrastructure import (
    PostgresFiscalCockpitReader,
    TaxRuleRepository,
)
from erp.modules.procurement.application import (
    PROCUREMENT_RFQ_READ,
    ProcurementAuthorization,
    ProcurementCockpitRfq,
    ProcurementCockpitService,
    ProcurementCockpitSnapshot,
)
from erp.modules.procurement.infrastructure import (
    PostgresProcurementCockpitReader,
    RequestForQuotationRepository,
)
from erp.platform.config import Settings
from erp.platform.database import ManagedDatabase
from tests.integration.test_payment_request_repository import payment_request_fixture
from tests.integration.test_rfq_repository import rfq_fixture
from tests.integration.test_tax_rule_repository import tax_rule_fixture

pytestmark = pytest.mark.integration

TOKEN = "triple-track-cockpit-token"
GENERATED_AT = datetime(2026, 11, 12, 14, 30, tzinfo=UTC)


class AvailableDatabase(ManagedDatabase):
    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == TOKEN else None


class DirectoryStub:
    def __init__(self, company: Company) -> None:
        self.company = company

    async def list_companies(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Company, ...]:
        if self.company.id not in context.company_ids:
            return ()
        if status is not None and self.company.status is not status:
            return ()
        return (self.company,)


class FiscalReaderStub:
    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> FiscalCockpitSnapshot:
        del limit
        rule = FiscalCockpitRule(
            id=uuid4(),
            code="TRIB-SP",
            version_code="2026.1",
            status="ACTIVE",
            flow="OUTBOUND",
            ncm="95030099",
            cfop="5102",
            effective_from=date(2026, 1, 1),
            effective_until=None,
            icms_rate=Decimal("0.1800"),
            pis_rate=Decimal("0.0165"),
            cofins_rate=Decimal("0.0760"),
            ipi_rate=Decimal("0.0000"),
            version=2,
        )
        return FiscalCockpitSnapshot(company_id, generated_at, 1, 0, 1, 0, (rule,))


class ProcurementReaderStub:
    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> ProcurementCockpitSnapshot:
        del limit
        rfq = ProcurementCockpitRfq(
            id=uuid4(),
            code="RFQ-2026-0042",
            status="AWARDED",
            response_deadline=date(2026, 12, 1),
            item_count=3,
            invited_supplier_count=4,
            quote_count=3,
            comparable_quote_currency="BRL",
            lowest_quote_amount=Decimal("18450.00"),
            awarded_supplier_id=uuid4(),
            version=5,
        )
        return ProcurementCockpitSnapshot(
            company_id,
            generated_at,
            1,
            0,
            0,
            0,
            1,
            0,
            (rfq,),
        )


class FinanceReaderStub:
    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> FinanceCockpitSnapshot:
        del limit
        payment = FinanceCockpitPayment(
            id=uuid4(),
            code="PAYREQ-2026-0091",
            status="PENDING_APPROVAL",
            scheduled_on=date(2026, 12, 9),
            purpose="Pagamento de matéria-prima homologada",
            item_count=2,
            total_amount=Decimal("18450.00"),
            currency="BRL",
            requested_by=uuid4(),
            approved_by=None,
            version=2,
        )
        return FinanceCockpitSnapshot(
            company_id,
            generated_at,
            1,
            0,
            1,
            0,
            0,
            0,
            Decimal("18450.00"),
            Decimal("0.00"),
            (payment,),
        )


def _context(
    company_id: UUID,
    *,
    permissions: frozenset[PermissionCode] | None = None,
) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_3),
        permissions=permissions
        or frozenset(
            {
                ADMIN_COMPANY_READ,
                FISCAL_TAX_RULE_READ,
                PROCUREMENT_RFQ_READ,
                FINANCE_TREASURY_READ,
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _application() -> tuple[FastAPI, ResolverStub, Company]:
    company = Company.create(
        group_id=uuid4(),
        code="BIGSTAR",
        legal_name="Big Star Industria e Comercio Ltda",
        trade_name="Big Star",
        tax_id="04.252.011/0001-10",
        timezone="America/Sao_Paulo",
    )
    directory = DirectoryStub(company)
    companies = CompanyAccessService(directory)
    resolver = ResolverStub()
    resolver.context = _context(company.id)
    application = create_app(
        Settings.model_validate({"environment": "test"}),
        AvailableDatabase(),
        company_query_service=ListCompaniesService(directory),
        security_context_resolver=resolver,
        fiscal_cockpit=FiscalCockpitService(
            FiscalReaderStub(),
            FiscalAuthorization(companies),
        ),
        procurement_cockpit=ProcurementCockpitService(
            ProcurementReaderStub(),
            ProcurementAuthorization(companies),
        ),
        finance_cockpit=FinanceCockpitService(
            FinanceReaderStub(),
            FinanceAuthorization(companies),
        ),
    )
    return application, resolver, company


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _error_recorder(target: list[str]) -> Callable[[PlaywrightError], None]:
    def record(error: PlaywrightError) -> None:
        target.append(str(error))

    return record


def test_triple_track_cockpit_readers_use_tenant_bound_postgres_repositories() -> None:
    async def scenario() -> None:
        async with tax_rule_fixture() as (data, rule):
            async with data.database.session() as session, session.begin():
                await TaxRuleRepository(session, company_id=data.company_id).add(
                    rule,
                    actor_id=data.actor_id,
                )
            fiscal_reader = PostgresFiscalCockpitReader(data.database)
            fiscal_snapshot = await fiscal_reader.load(
                data.company_id,
                generated_at=GENERATED_AT,
                limit=100,
            )
            fiscal_hidden = await fiscal_reader.load(
                data.other_company_id,
                generated_at=GENERATED_AT,
                limit=100,
            )
            assert fiscal_snapshot.rules[0].code == rule.code
            assert fiscal_hidden.rules == ()

        async with rfq_fixture() as (data, rfq, _):
            async with data.database.session() as session, session.begin():
                await RequestForQuotationRepository(
                    session,
                    company_id=data.company_id,
                ).add(rfq, actor_id=data.actor_id)
            procurement_reader = PostgresProcurementCockpitReader(data.database)
            procurement_snapshot = await procurement_reader.load(
                data.company_id,
                generated_at=GENERATED_AT,
                limit=100,
            )
            procurement_hidden = await procurement_reader.load(
                data.other_company_id,
                generated_at=GENERATED_AT,
                limit=100,
            )
            assert procurement_snapshot.rfqs[0].code == rfq.code
            assert procurement_hidden.rfqs == ()

        async with payment_request_fixture() as (fixture, request):
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                await PaymentRequestRepository(
                    session,
                    company_id=data.company_id,
                ).add(request, actor_id=request.requested_by)
            finance_reader = PostgresFinanceCockpitReader(data.database)
            finance_snapshot = await finance_reader.load(
                data.company_id,
                generated_at=GENERATED_AT,
                limit=100,
            )
            finance_hidden = await finance_reader.load(
                data.other_company_id,
                generated_at=GENERATED_AT,
                limit=100,
            )
            assert finance_snapshot.payments[0].code == request.code
            assert finance_hidden.payments == ()

    asyncio.run(scenario())


def test_triple_track_cockpit_apis_enforce_rbac_tenant_and_no_store() -> None:
    application, resolver, company = _application()
    with TestClient(application) as client:
        cases = (
            ("fiscal", "rules", "TRIB-SP"),
            ("procurement", "rfqs", "RFQ-2026-0042"),
            ("finance", "payments", "PAYREQ-2026-0091"),
        )
        for module, collection, expected_code in cases:
            response = client.get(
                f"/api/v1/{module}/cockpit",
                headers=_headers(),
                params={"company_id": str(company.id)},
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["company_id"] == str(company.id)
            assert response.json()[collection][0]["code"] == expected_code

        foreign = client.get(
            "/api/v1/fiscal/cockpit",
            headers=_headers(),
            params={"company_id": str(uuid4())},
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

        resolver.context = _context(
            company.id,
            permissions=frozenset({ADMIN_COMPANY_READ}),
        )
        for module in ("fiscal", "procurement", "finance"):
            denied = client.get(
                f"/api/v1/{module}/cockpit",
                headers=_headers(),
                params={"company_id": str(company.id)},
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"


@dataclass(frozen=True, slots=True)
class BrowserServer:
    url: str
    resolver: ResolverStub
    company: Company


@contextmanager
def cockpit_server() -> Iterator[BrowserServer]:
    application, resolver, company = _application()
    with socket.socket() as listener:
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
                    raise RuntimeError("Triple-track cockpit server failed to start.")
                time.sleep(0.02)
            yield BrowserServer(
                f"http://127.0.0.1:{listener.getsockname()[1]}",
                resolver,
                company,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Browser server must stop before cleanup."


@pytest.mark.browser
def test_triple_track_cockpits_chromium_desktop_mobile_and_denied_rbac() -> None:
    with cockpit_server() as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        artifacts = Path("test-results")
        artifacts.mkdir(exist_ok=True)
        cases = (
            ("fiscal", "Conectar ao Fiscal", "Mapa de vigências tributárias", "TRIB-SP"),
            (
                "procurement",
                "Conectar a Compras",
                "Pipeline competitivo de fornecedores",
                "RFQ-2026-0042",
            ),
            (
                "finance",
                "Conectar ao Financeiro",
                "Fila de decisões financeiras",
                "PAYREQ-2026-0091",
            ),
        )
        for module, connect, heading, expected in cases:
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            failures: list[str] = []
            page.on("pageerror", _error_recorder(failures))
            response = page.goto(f"{server.url}/ui/{module}/cockpit")
            assert response is not None
            assert response.ok
            page.get_by_label("Token de acesso").fill(TOKEN)
            page.get_by_role("button", name=connect).click()
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
            expect(page.locator("#queue-body")).to_contain_text(expected)
            page.screenshot(
                path=str(artifacts / f"triple-track-{module}-desktop.png"),
                full_page=True,
            )
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            page.screenshot(
                path=str(artifacts / f"triple-track-{module}-mobile.png"),
                full_page=True,
            )
            assert failures == []
            page.close()

        server.resolver.context = _context(
            server.company.id,
            permissions=frozenset({ADMIN_COMPANY_READ}),
        )
        denied = browser.new_page(viewport={"width": 1024, "height": 768})
        denied.goto(f"{server.url}/ui/finance/cockpit")
        denied.get_by_label("Token de acesso").fill(TOKEN)
        denied.get_by_role("button", name="Conectar ao Financeiro").click()
        expect(
            denied.get_by_role("heading", name="Permissão de tesouraria necessária")
        ).to_be_visible()
        browser.close()


def test_triple_track_assets_keep_tokens_ephemeral_and_use_official_contracts() -> None:
    root = Path("erp/apps/web/static")
    script = (root / "triple-track-cockpit.js").read_text(encoding="utf-8")
    assert "fiscal/cockpit" in script
    assert "procurement/cockpit" in script
    assert "finance/cockpit" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    for module in ("fiscal", "procurement", "finance"):
        html = (root / module / "cockpit" / "index.html").read_text(encoding="utf-8")
        assert 'autocomplete="off"' in html
        assert "/ui/triple-track-cockpit.js" in html


__all__: list[str] = []
