"""Public M11 integration contracts."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.fiscal.contracts import (
    AuthorizedFiscalDocumentFact,
    FiscalOriginReference,
    FiscalOriginType,
)
from erp.modules.fiscal.domain import (
    InvalidFiscalContractError,
    NFeAccessKey,
    TaxComponentSnapshot,
    TaxKind,
    TaxSnapshot,
)
from tests.unit.modules.fiscal.test_access_key import _key


def _snapshot() -> TaxSnapshot:
    def tax(kind: TaxKind) -> TaxComponentSnapshot:
        return TaxComponentSnapshot.create(
            kind=kind, tax_code="00", taxable_base="0", rate="0", amount="0"
        )

    return TaxSnapshot(
        icms=tax(TaxKind.ICMS),
        pis=tax(TaxKind.PIS),
        cofins=tax(TaxKind.COFINS),
        ipi=tax(TaxKind.IPI),
    )


def test_authorized_fact_preserves_tenant_origin_and_snapshot() -> None:
    company_id = uuid4()
    origin = FiscalOriginReference(company_id, FiscalOriginType.GOODS_RECEIPT, uuid4(), 4)
    fact = AuthorizedFiscalDocumentFact(
        company_id=company_id,
        fiscal_document_id=uuid4(),
        access_key=NFeAccessKey(_key()),
        origin=origin,
        total_amount=Decimal("123.45"),
        tax_snapshot=_snapshot(),
    )

    assert fact.origin.source_type is FiscalOriginType.GOODS_RECEIPT
    with pytest.raises(FrozenInstanceError):
        fact.total_amount = Decimal("0")  # type: ignore[misc]


def test_contract_rejects_cross_company_origin() -> None:
    with pytest.raises(InvalidFiscalContractError):
        AuthorizedFiscalDocumentFact(
            company_id=uuid4(),
            fiscal_document_id=uuid4(),
            access_key=NFeAccessKey(_key()),
            origin=FiscalOriginReference(uuid4(), FiscalOriginType.PURCHASE_ORDER, uuid4(), 1),
            total_amount=Decimal("1"),
            tax_snapshot=_snapshot(),
        )


def test_contract_rejects_invalid_version_and_amount() -> None:
    company_id = uuid4()
    with pytest.raises(InvalidFiscalContractError):
        FiscalOriginReference(company_id, FiscalOriginType.SALES_ORDER, uuid4(), 0)
    origin = FiscalOriginReference(company_id, FiscalOriginType.SALES_ORDER, uuid4(), 1)
    with pytest.raises(InvalidFiscalContractError):
        AuthorizedFiscalDocumentFact(
            company_id=company_id,
            fiscal_document_id=uuid4(),
            access_key=NFeAccessKey(_key()),
            origin=origin,
            total_amount=Decimal("NaN"),
            tax_snapshot=_snapshot(),
        )
