"""Immutable M12 contracts for M11/M6 payable provisioning facts."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.contracts import (
    ApprovedPurchaseOrderReference,
    AuthorizedFiscalDocumentReference,
    PayableProvisionRequest,
)
from erp.modules.finance.domain import InvalidFinanceContractError

ACCESS_KEY = "1" * 44


def _fiscal(company_id=None) -> AuthorizedFiscalDocumentReference:  # type: ignore[no-untyped-def]
    return AuthorizedFiscalDocumentReference(
        company_id=company_id or uuid4(),
        fiscal_document_id=uuid4(),
        access_key=ACCESS_KEY,
        authorization_protocol="135260000000001",
        supplier_tax_id="12.345.678/0001-95",
        total_amount=Decimal("123.45"),
    )


def _order(company_id=None) -> ApprovedPurchaseOrderReference:  # type: ignore[no-untyped-def]
    return ApprovedPurchaseOrderReference(
        company_id=company_id or uuid4(),
        purchase_order_id=uuid4(),
        supplier_id=uuid4(),
        supplier_tax_id="12.345.678/0001-95",
        order_number="PO-156",
        approved_version=3,
        total_amount=Decimal("123.45"),
        currency="brl",
    )


def test_provision_contract_preserves_immutable_tenant_bound_references() -> None:
    company_id = uuid4()
    request = PayableProvisionRequest(
        request_id=uuid4(),
        company_id=company_id,
        requested_by=uuid4(),
        fiscal_document=_fiscal(company_id),
        purchase_order=_order(company_id),
    )

    assert request.fiscal_document.supplier_tax_id == "12345678000195"
    assert request.purchase_order.currency == "BRL"
    assert request.fingerprint.startswith(f"M12:{company_id}:{ACCESS_KEY}:")
    with pytest.raises(FrozenInstanceError):
        request.company_id = uuid4()  # type: ignore[misc]


def test_provision_contract_rejects_cross_company_references() -> None:
    with pytest.raises(InvalidFinanceContractError, match="share company_id"):
        PayableProvisionRequest(
            request_id=uuid4(),
            company_id=uuid4(),
            requested_by=uuid4(),
            fiscal_document=_fiscal(),
            purchase_order=_order(),
        )


def test_provision_contract_rejects_a_different_supplier_identity() -> None:
    company_id = uuid4()
    fiscal = _fiscal(company_id)
    order = ApprovedPurchaseOrderReference(
        company_id=company_id,
        purchase_order_id=uuid4(),
        supplier_id=uuid4(),
        supplier_tax_id="98765432000110",
        order_number="PO-OTHER-SUPPLIER",
        approved_version=1,
        total_amount=Decimal("123.45"),
    )
    with pytest.raises(InvalidFinanceContractError, match="same supplier tax ID"):
        PayableProvisionRequest(
            request_id=uuid4(),
            company_id=company_id,
            requested_by=uuid4(),
            fiscal_document=fiscal,
            purchase_order=order,
        )


@pytest.mark.parametrize("access_key", ["", "1" * 43, "A" * 44])
def test_fiscal_reference_requires_an_authorized_nfe_identity(access_key: str) -> None:
    with pytest.raises(InvalidFinanceContractError, match="44 digits"):
        AuthorizedFiscalDocumentReference(
            company_id=uuid4(),
            fiscal_document_id=uuid4(),
            access_key=access_key,
            authorization_protocol="135260000000001",
            supplier_tax_id="12345678000195",
            total_amount=Decimal("1.00"),
        )


def test_contracts_reject_invalid_versions_amounts_and_shapes() -> None:
    with pytest.raises(InvalidFinanceContractError, match="approved_version"):
        ApprovedPurchaseOrderReference(
            company_id=uuid4(),
            purchase_order_id=uuid4(),
            supplier_id=uuid4(),
            supplier_tax_id="12345678000195",
            order_number="PO-X",
            approved_version=0,
            total_amount=Decimal("1.00"),
        )
    with pytest.raises(InvalidFinanceContractError, match="positive"):
        ApprovedPurchaseOrderReference(
            company_id=uuid4(),
            purchase_order_id=uuid4(),
            supplier_id=uuid4(),
            supplier_tax_id="12345678000195",
            order_number="PO-X",
            approved_version=1,
            total_amount=Decimal("0"),
        )
    with pytest.raises(InvalidFinanceContractError, match="currency"):
        ApprovedPurchaseOrderReference(
            company_id=uuid4(),
            purchase_order_id=uuid4(),
            supplier_id=uuid4(),
            supplier_tax_id="12345678000195",
            order_number="PO-X",
            approved_version=1,
            total_amount=Decimal("1.00"),
            currency="R$",
        )
    with pytest.raises(InvalidFinanceContractError, match="authorized fiscal"):
        PayableProvisionRequest(
            request_id=uuid4(),
            company_id=uuid4(),
            requested_by=uuid4(),
            fiscal_document=cast(AuthorizedFiscalDocumentReference, object()),
            purchase_order=_order(),
        )
    company_id = uuid4()
    with pytest.raises(InvalidFinanceContractError, match="approved purchase order"):
        PayableProvisionRequest(
            request_id=uuid4(),
            company_id=company_id,
            requested_by=uuid4(),
            fiscal_document=_fiscal(company_id),
            purchase_order=cast(ApprovedPurchaseOrderReference, object()),
        )


def test_contract_helpers_fail_closed_for_malformed_boundary_payloads() -> None:
    with pytest.raises(InvalidFinanceContractError, match="non-zero UUID"):
        _fiscal(UUID(int=0))
    with pytest.raises(InvalidFinanceContractError, match="finite Decimal"):
        AuthorizedFiscalDocumentReference(
            company_id=uuid4(),
            fiscal_document_id=uuid4(),
            access_key=ACCESS_KEY,
            authorization_protocol="135260000000001",
            supplier_tax_id="12345678000195",
            total_amount=Decimal("NaN"),
        )
    with pytest.raises(InvalidFinanceContractError, match="supported monetary precision"):
        AuthorizedFiscalDocumentReference(
            company_id=uuid4(),
            fiscal_document_id=uuid4(),
            access_key=ACCESS_KEY,
            authorization_protocol="135260000000001",
            supplier_tax_id="12345678000195",
            total_amount=Decimal("12345678901234567890123456789"),
        )
    with pytest.raises(InvalidFinanceContractError, match="authorization_protocol"):
        AuthorizedFiscalDocumentReference(
            company_id=uuid4(),
            fiscal_document_id=uuid4(),
            access_key=ACCESS_KEY,
            authorization_protocol="",
            supplier_tax_id="12345678000195",
            total_amount=Decimal("1.00"),
        )
    with pytest.raises(InvalidFinanceContractError, match="supplier_tax_id"):
        AuthorizedFiscalDocumentReference(
            company_id=uuid4(),
            fiscal_document_id=uuid4(),
            access_key=ACCESS_KEY,
            authorization_protocol="135260000000001",
            supplier_tax_id=cast(str, object()),
            total_amount=Decimal("1.00"),
        )
    with pytest.raises(InvalidFinanceContractError, match="order_number"):
        ApprovedPurchaseOrderReference(
            company_id=uuid4(),
            purchase_order_id=uuid4(),
            supplier_id=uuid4(),
            supplier_tax_id="12345678000195",
            order_number="",
            approved_version=1,
            total_amount=Decimal("1.00"),
        )
    with pytest.raises(InvalidFinanceContractError, match="currency"):
        ApprovedPurchaseOrderReference(
            company_id=uuid4(),
            purchase_order_id=uuid4(),
            supplier_id=uuid4(),
            supplier_tax_id="12345678000195",
            order_number="PO-X",
            approved_version=1,
            total_amount=Decimal("1.00"),
            currency=cast(str, object()),
        )
