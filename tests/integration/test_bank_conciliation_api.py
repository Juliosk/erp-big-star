"""M12 bank-reconciliation REST API integration against real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.finance.application import (
    FINANCE_RECONCILIATION_EXECUTE,
    FINANCE_RECONCILIATION_IMPORT,
    FINANCE_RECONCILIATION_READ,
    BankReconciliationApplicationService,
    FinanceAuthorization,
)
from erp.modules.finance.infrastructure import (
    PayableInstallmentModel,
    PayableModel,
    PostgresBankReconciliationStore,
)
from erp.platform.config import get_settings
from tests.integration.test_bank_statement_repository import bank_statement_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "bank-reconciliation-test-token" else None


@contextmanager
def reconciliation_api() -> Iterator[
    tuple[TestClient, ProcurementFixture, ResolverStub, UUID, UUID]
]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = bank_statement_fixture()
        data = client.portal.call(manager.__aenter__)
        exact_candidate_id, mismatched_candidate_id = client.portal.call(
            _seed_paid_candidates,
            data,
        )
        authorization = FinanceAuthorization(
            CompanyAccessService(PostgresCorporateDirectory(data.database))
        )
        application = cast(FastAPI, client.app)
        application.state.finance_reconciliation = BankReconciliationApplicationService(
            PostgresBankReconciliationStore(data.database),
            authorization,
        )
        resolver.context = _context(data.actor_id, data.company_id)
        try:
            yield client, data, resolver, exact_candidate_id, mismatched_candidate_id
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


async def _seed_paid_candidates(data: ProcurementFixture) -> tuple[UUID, UUID]:
    values = (
        ("PAY-API-183", Decimal("100.00")),
        ("PAY-MISMATCH-183", Decimal("110.00")),
    )
    candidate_ids = []
    async with data.database.session() as session, session.begin():
        for document_number, amount in values:
            payable_id = uuid4()
            installment_id = uuid4()
            session.add(
                PayableModel(
                    id=payable_id,
                    company_id=data.company_id,
                    document_number=document_number,
                    supplier_id=uuid4(),
                    supplier_tax_id="12345678000195",
                    provisional_entry_id=None,
                    currency="BRL",
                    nominal_amount=amount,
                    interest_amount=Decimal("0.00"),
                    discount_amount=Decimal("0.00"),
                    surcharge_amount=Decimal("0.00"),
                    status="PAID",
                    decision_by=uuid4(),
                    decision_reason="Bank reconciliation fixture",
                    version=1,
                    created_by=data.actor_id,
                    updated_by=data.actor_id,
                )
            )
            await session.flush()
            session.add(
                PayableInstallmentModel(
                    id=installment_id,
                    company_id=data.company_id,
                    payable_id=payable_id,
                    installment_number=1,
                    due_date=date(2026, 10, 27),
                    amount=amount,
                    status="PAID",
                    schedule_id=uuid4(),
                    paid_on=date(2026, 10, 28),
                    payment_reference=document_number,
                    created_by=data.actor_id,
                    updated_by=data.actor_id,
                )
            )
            candidate_ids.append(installment_id)
        await session.flush()
    return candidate_ids[0], candidate_ids[1]


def _context(actor_id: UUID, company_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(
            {
                FINANCE_RECONCILIATION_READ,
                FINANCE_RECONCILIATION_IMPORT,
                FINANCE_RECONCILIATION_EXECUTE,
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _headers(**values: str) -> dict[str, str]:
    return {"Authorization": "Bearer bank-reconciliation-test-token", **values}


def _ofx() -> bytes:
    return b"""OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>001<ACCTID>123456-7</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20261001000000<DTEND>20261031235959
<STMTTRN><TRNTYPE>PAYMENT<DTPOSTED>20261028120000<TRNAMT>-100.00
<FITID>API-183-PAYMENT<CHECKNUM>PAY-API-183<MEMO>Pagamento fornecedor</STMTTRN>
<STMTTRN><TRNTYPE>FEE<DTPOSTED>20261028130000<TRNAMT>-5.00
<FITID>API-183-FEE<MEMO>Tarifa bancaria</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>895.00</LEDGERBAL></STMTRS></STMTTRNRS>
</BANKMSGSRSV1></OFX>"""


def _upload(client: TestClient, data: ProcurementFixture) -> Any:
    return client.post(
        "/api/v1/finance/reconciliation/statements/upload",
        headers=_headers(),
        data={
            "company_id": str(data.company_id),
            "bank_account_id": str(uuid4()),
            "source": "OFX",
        },
        files={"file": ("statement-183.ofx", _ofx(), "application/x-ofx")},
    )


def test_multipart_ofx_upload_replay_listing_and_tenant_isolation() -> None:
    with reconciliation_api() as (client, data, resolver, _, _):
        account_id = uuid4()
        request = {
            "company_id": str(data.company_id),
            "bank_account_id": str(account_id),
            "source": "OFX",
        }
        first = client.post(
            "/api/v1/finance/reconciliation/statements/upload",
            headers=_headers(),
            data=request,
            files={"file": ("statement-183.ofx", _ofx(), "application/x-ofx")},
        )
        assert first.status_code == 201, first.text
        assert first.headers["etag"] == '"1"'
        assert first.headers["idempotency-replayed"] == "false"
        assert len(first.json()["movements"]) == 2

        replay = client.post(
            "/api/v1/finance/reconciliation/statements/upload",
            headers=_headers(),
            data=request,
            files={"file": ("statement-183.ofx", _ofx(), "application/x-ofx")},
        )
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["statement"]["id"] == first.json()["statement"]["id"]

        listing = client.get(
            "/api/v1/finance/reconciliation/statements",
            headers=_headers(),
            params={"company_id": str(data.company_id), "bank_account_id": str(account_id)},
        )
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["data"]] == [
            first.json()["statement"]["id"]
        ]
        movements = client.get(
            "/api/v1/finance/reconciliation/movements",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "status": "PENDING",
                "statement_id": first.json()["statement"]["id"],
                "page_size": 1,
            },
        )
        assert movements.status_code == 200
        assert movements.json()["has_more"] is True
        assert movements.json()["data"][0]["statement_id"] == first.json()["statement"]["id"]

        resolver.context = _context(data.actor_id, data.other_company_id)
        hidden = client.get(
            f"/api/v1/finance/reconciliation/statements/{first.json()['statement']['id']}",
            headers=_headers(),
            params={"company_id": str(data.other_company_id)},
        )
        assert hidden.status_code == 404


def test_simulation_then_application_reconciles_candidate_and_preserves_explanations() -> None:
    with reconciliation_api() as (client, data, _, exact_candidate_id, _):
        uploaded = _upload(client, data)
        assert uploaded.status_code == 201, uploaded.text
        statement_id = uploaded.json()["statement"]["id"]

        simulation = client.post(
            f"/api/v1/finance/reconciliation/statements/{statement_id}/match",
            headers=_headers(**{"If-Match": '"1"'}),
            params={"company_id": str(data.company_id)},
            json={"mode": "SIMULATE"},
        )
        assert simulation.status_code == 200, simulation.text
        assert simulation.headers["etag"] == '"1"'
        outcomes = simulation.json()["outcomes"]
        assert outcomes[0]["classification"] == "RECONCILED"
        assert outcomes[0]["candidate_id"] == str(exact_candidate_id)
        assert outcomes[1]["classification"] == "DIRECT_BANK_FEE"

        pending = client.get(
            f"/api/v1/finance/reconciliation/statements/{statement_id}/movements",
            headers=_headers(),
            params={"company_id": str(data.company_id), "status": "PENDING"},
        )
        assert pending.status_code == 200
        assert len(pending.json()["data"]) == 2

        applied = client.post(
            f"/api/v1/finance/reconciliation/statements/{statement_id}/match",
            headers=_headers(**{"If-Match": '"1"'}),
            params={"company_id": str(data.company_id)},
            json={"mode": "APPLY"},
        )
        assert applied.status_code == 200, applied.text
        assert applied.headers["etag"] == '"2"'
        assert applied.json()["reconciled_count"] == 1

        reconciled = client.get(
            f"/api/v1/finance/reconciliation/statements/{statement_id}/movements",
            headers=_headers(),
            params={"company_id": str(data.company_id), "status": "RECONCILED"},
        )
        assert reconciled.status_code == 200
        assert [item["matched_reference_id"] for item in reconciled.json()["data"]] == [
            str(exact_candidate_id)
        ]


def test_manual_resolution_enforces_conflict_justification_etag_and_rbac() -> None:
    with reconciliation_api() as (
        client,
        data,
        resolver,
        _,
        mismatched_candidate_id,
    ):
        uploaded = _upload(client, data)
        assert uploaded.status_code == 201, uploaded.text
        statement_id = uploaded.json()["statement"]["id"]
        movement_id = uploaded.json()["movements"][0]["id"]
        endpoint = (
            f"/api/v1/finance/reconciliation/statements/{statement_id}"
            f"/movements/{movement_id}/resolve"
        )

        missing_precondition = client.post(
            endpoint,
            headers=_headers(),
            params={"company_id": str(data.company_id)},
            json={"mode": "FORCE_MATCH", "candidate_id": str(mismatched_candidate_id)},
        )
        assert missing_precondition.status_code == 428

        conflict = client.post(
            endpoint,
            headers=_headers(**{"If-Match": '"1"'}),
            params={"company_id": str(data.company_id)},
            json={"mode": "ACCEPT_MATCH", "candidate_id": str(mismatched_candidate_id)},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "MATCH_CONFLICT"

        forced = client.post(
            endpoint,
            headers=_headers(**{"If-Match": '"1"'}),
            params={"company_id": str(data.company_id)},
            json={
                "mode": "FORCE_MATCH",
                "candidate_id": str(mismatched_candidate_id),
                "justification": "Divergencia aprovada pela tesouraria responsavel.",
            },
        )
        assert forced.status_code == 200, forced.text
        assert forced.headers["etag"] == '"2"'
        assert forced.json()["outcomes"][0]["candidate_id"] == str(
            mismatched_candidate_id
        )

        stale = client.post(
            f"/api/v1/finance/reconciliation/statements/{statement_id}/match",
            headers=_headers(**{"If-Match": '"1"'}),
            params={"company_id": str(data.company_id)},
            json={"mode": "APPLY"},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

        current_context = resolver.context
        assert current_context is not None
        resolver.context = SecurityContext(
            principal=current_context.principal,
            permissions=frozenset({FINANCE_RECONCILIATION_READ}),
            scopes=current_context.scopes,
        )
        denied = client.post(
            f"/api/v1/finance/reconciliation/statements/{statement_id}/match",
            headers=_headers(**{"If-Match": '"2"'}),
            params={"company_id": str(data.company_id)},
            json={"mode": "SIMULATE"},
        )
        assert denied.status_code == 403


def test_direct_fee_resolution_is_explainable_without_creating_a_false_title_match() -> None:
    with reconciliation_api() as (client, data, _, _, _):
        uploaded = _upload(client, data)
        assert uploaded.status_code == 201, uploaded.text
        statement_id = uploaded.json()["statement"]["id"]
        fee = uploaded.json()["movements"][1]

        resolved = client.post(
            f"/api/v1/finance/reconciliation/statements/{statement_id}"
            f"/movements/{fee['id']}/resolve",
            headers=_headers(**{"If-Match": '"1"'}),
            params={"company_id": str(data.company_id)},
            json={
                "mode": "DIRECT_ENTRY",
                "justification": "Tarifa bancaria classificada para lancamento direto.",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.headers["etag"] == '"1"'
        assert resolved.json()["outcomes"] == [
            {
                "movement_id": fee["id"],
                "classification": "DIRECT_BANK_FEE",
                "reason": None,
                "candidate_id": None,
                "candidate_source": None,
                "candidate_count": 0,
            }
        ]


__all__: list[str] = []
