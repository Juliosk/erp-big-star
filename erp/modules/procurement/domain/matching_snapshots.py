"""Immutable M6/M11/M12 source snapshots used by three-way matching."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Self
from uuid import UUID

from erp.modules.procurement.domain.exceptions import InvalidMatchingSnapshotError

_MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class VersionedArtifactReference:
    """Stable identity and optimistic version captured from an external owner."""

    id: UUID
    version: int

    def __post_init__(self) -> None:
        _uuid(self.id, "artifact id")
        if type(self.version) is not int or self.version < 1:
            raise InvalidMatchingSnapshotError("artifact version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class PurchaseOrderMatchSnapshot:
    """Immutable M6 purchase-order header at matching time."""

    company_id: UUID
    purchase_order: VersionedArtifactReference
    supplier_id: UUID
    currency: str
    total_amount: Decimal
    captured_at: datetime

    @classmethod
    def capture(
        cls,
        *,
        company_id: UUID,
        purchase_order_id: UUID,
        purchase_order_version: int,
        supplier_id: UUID,
        currency: str,
        total_amount: Decimal | str | int,
        captured_at: datetime | None = None,
    ) -> Self:
        return cls(
            company_id=company_id,
            purchase_order=VersionedArtifactReference(purchase_order_id, purchase_order_version),
            supplier_id=supplier_id,
            currency=currency,
            total_amount=_money(total_amount, "purchase order total"),
            captured_at=captured_at or datetime.now(UTC),
        )

    def __post_init__(self) -> None:
        _snapshot_header(
            self.company_id,
            self.supplier_id,
            self.currency,
            self.total_amount,
            self.captured_at,
        )
        if not isinstance(self.purchase_order, VersionedArtifactReference):
            raise InvalidMatchingSnapshotError(
                "purchase_order must be a VersionedArtifactReference."
            )
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "total_amount", _money(self.total_amount, "purchase order total"))


@dataclass(frozen=True, slots=True)
class ReceivingFiscalMatchSnapshot:
    """Immutable M6 receipt and M11 inbound fiscal header snapshot."""

    company_id: UUID
    goods_receipts: tuple[VersionedArtifactReference, ...]
    fiscal_documents: tuple[VersionedArtifactReference, ...]
    supplier_id: UUID
    currency: str
    invoiced_total_amount: Decimal
    captured_at: datetime

    @classmethod
    def capture(
        cls,
        *,
        company_id: UUID,
        goods_receipts: tuple[VersionedArtifactReference, ...],
        fiscal_documents: tuple[VersionedArtifactReference, ...],
        supplier_id: UUID,
        currency: str,
        invoiced_total_amount: Decimal | str | int,
        captured_at: datetime | None = None,
    ) -> Self:
        return cls(
            company_id=company_id,
            goods_receipts=goods_receipts,
            fiscal_documents=fiscal_documents,
            supplier_id=supplier_id,
            currency=currency,
            invoiced_total_amount=_money(invoiced_total_amount, "invoiced total amount"),
            captured_at=captured_at or datetime.now(UTC),
        )

    def __post_init__(self) -> None:
        _snapshot_header(
            self.company_id,
            self.supplier_id,
            self.currency,
            self.invoiced_total_amount,
            self.captured_at,
        )
        _reference_tuple(self.goods_receipts, "goods_receipts")
        _reference_tuple(self.fiscal_documents, "fiscal_documents")
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(
            self,
            "invoiced_total_amount",
            _money(self.invoiced_total_amount, "invoiced total amount"),
        )


@dataclass(frozen=True, slots=True)
class FinancialMatchSnapshot:
    """Immutable M12 provision/payable header at matching time."""

    company_id: UUID
    provisional_entry: VersionedArtifactReference
    payable: VersionedArtifactReference | None
    supplier_id: UUID
    currency: str
    obligation_amount: Decimal
    captured_at: datetime

    @classmethod
    def capture(
        cls,
        *,
        company_id: UUID,
        provisional_entry_id: UUID,
        provisional_entry_version: int,
        payable_id: UUID | None,
        payable_version: int | None,
        supplier_id: UUID,
        currency: str,
        obligation_amount: Decimal | str | int,
        captured_at: datetime | None = None,
    ) -> Self:
        if (payable_id is None) != (payable_version is None):
            raise InvalidMatchingSnapshotError(
                "payable id and version must be both present or both absent."
            )
        return cls(
            company_id=company_id,
            provisional_entry=VersionedArtifactReference(
                provisional_entry_id, provisional_entry_version
            ),
            payable=(
                VersionedArtifactReference(payable_id, payable_version)
                if payable_id is not None and payable_version is not None
                else None
            ),
            supplier_id=supplier_id,
            currency=currency,
            obligation_amount=_money(obligation_amount, "financial obligation amount"),
            captured_at=captured_at or datetime.now(UTC),
        )

    def __post_init__(self) -> None:
        _snapshot_header(
            self.company_id,
            self.supplier_id,
            self.currency,
            self.obligation_amount,
            self.captured_at,
        )
        if not isinstance(self.provisional_entry, VersionedArtifactReference):
            raise InvalidMatchingSnapshotError(
                "provisional_entry must be a VersionedArtifactReference."
            )
        if self.payable is not None and not isinstance(self.payable, VersionedArtifactReference):
            raise InvalidMatchingSnapshotError(
                "payable must be a VersionedArtifactReference when present."
            )
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(
            self,
            "obligation_amount",
            _money(self.obligation_amount, "financial obligation amount"),
        )


def _snapshot_header(
    company_id: UUID,
    supplier_id: UUID,
    currency: str,
    amount: Decimal,
    captured_at: datetime,
) -> None:
    _uuid(company_id, "company_id")
    _uuid(supplier_id, "supplier_id")
    _currency(currency)
    _money(amount, "snapshot amount")
    _timestamp(captured_at, "captured_at")


def _reference_tuple(references: tuple[VersionedArtifactReference, ...], field: str) -> None:
    if not isinstance(references, tuple) or not references:
        raise InvalidMatchingSnapshotError(f"{field} must be a non-empty tuple.")
    if any(not isinstance(reference, VersionedArtifactReference) for reference in references):
        raise InvalidMatchingSnapshotError(
            f"every {field} member must be a VersionedArtifactReference."
        )
    if len({reference.id for reference in references}) != len(references):
        raise InvalidMatchingSnapshotError(f"{field} identities must be unique.")


def _uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise InvalidMatchingSnapshotError(f"{field} must be a UUID.")
    return value


def _money(value: Decimal | str | int, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise InvalidMatchingSnapshotError(f"{field} must be a valid decimal.") from error
    if not parsed.is_finite():
        raise InvalidMatchingSnapshotError(f"{field} must be finite.")
    try:
        normalized = parsed.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise InvalidMatchingSnapshotError(f"{field} must be a valid decimal.") from error
    if normalized <= 0:
        raise InvalidMatchingSnapshotError(f"{field} must be positive.")
    return normalized


def _currency(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value.strip().upper()) is None:
        raise InvalidMatchingSnapshotError("currency must use ISO 4217 alpha-3 format.")
    return value.strip().upper()


def _timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidMatchingSnapshotError(f"{field} must be timezone-aware.")
    return value


__all__ = [
    "FinancialMatchSnapshot",
    "PurchaseOrderMatchSnapshot",
    "ReceivingFiscalMatchSnapshot",
    "VersionedArtifactReference",
]
