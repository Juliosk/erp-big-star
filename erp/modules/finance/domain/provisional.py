"""Pure provisional financial entry generated from M11 or M6 facts."""

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.finance.domain.exceptions import InvalidProvisionalEntryError

_CENT = Decimal("0.01")


class ProvisionalEntryOrigin(StrEnum):
    AUTHORIZED_FISCAL_DOCUMENT = "AUTHORIZED_FISCAL_DOCUMENT"
    APPROVED_PURCHASE_ORDER = "APPROVED_PURCHASE_ORDER"


class ProvisionalEntryStatus(StrEnum):
    OPEN = "OPEN"
    CONVERTED = "CONVERTED"
    VOIDED = "VOIDED"


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidProvisionalEntryError(f"{field} must be a non-zero UUID.")
    return value


def _money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidProvisionalEntryError("amount must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidProvisionalEntryError("amount uses unsupported monetary precision.") from error
    if normalized <= 0 or normalized != value:
        raise InvalidProvisionalEntryError(
            "amount must be positive with at most two decimal places."
        )
    return normalized


def _tax_id(value: str) -> str:
    source = value if isinstance(value, str) else ""
    normalized = "".join(character for character in source if character.isdigit())
    if len(normalized) not in {11, 14}:
        raise InvalidProvisionalEntryError("supplier_tax_id must be a CPF or CNPJ.")
    return normalized


def _currency(value: str) -> str:
    normalized = value.strip().upper() if isinstance(value, str) else ""
    if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
        raise InvalidProvisionalEntryError("currency must be a three-letter ASCII code.")
    return normalized


@dataclass(frozen=True, slots=True)
class ProvisionalFinancialEntry:
    id: UUID
    company_id: UUID
    origin: ProvisionalEntryOrigin
    source_id: UUID
    source_version: int
    supplier_id: UUID
    supplier_tax_id: str
    amount: Decimal
    currency: str
    created_by: UUID
    status: ProvisionalEntryStatus
    payable_id: UUID | None
    void_reason: str | None
    version: int

    def __post_init__(self) -> None:
        _uuid(self.id, "id")
        _uuid(self.company_id, "company_id")
        _uuid(self.source_id, "source_id")
        _uuid(self.supplier_id, "supplier_id")
        _uuid(self.created_by, "created_by")
        if not isinstance(self.origin, ProvisionalEntryOrigin):
            raise InvalidProvisionalEntryError("origin must be an official source type.")
        if type(self.source_version) is not int or self.source_version < 1:
            raise InvalidProvisionalEntryError("source_version must be a positive integer.")
        object.__setattr__(self, "supplier_tax_id", _tax_id(self.supplier_tax_id))
        object.__setattr__(self, "amount", _money(self.amount))
        object.__setattr__(self, "currency", _currency(self.currency))
        if not isinstance(self.status, ProvisionalEntryStatus):
            raise InvalidProvisionalEntryError("status must be an official provisional status.")
        if type(self.version) is not int or self.version < 1:
            raise InvalidProvisionalEntryError("version must be a positive integer.")
        self._validate_state_metadata()

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        origin: ProvisionalEntryOrigin,
        source_id: UUID,
        source_version: int,
        supplier_id: UUID,
        supplier_tax_id: str,
        amount: Decimal,
        created_by: UUID,
        currency: str = "BRL",
    ) -> ProvisionalFinancialEntry:
        return cls(
            id=uuid4(),
            company_id=company_id,
            origin=origin,
            source_id=source_id,
            source_version=source_version,
            supplier_id=supplier_id,
            supplier_tax_id=supplier_tax_id,
            amount=amount,
            currency=currency,
            created_by=created_by,
            status=ProvisionalEntryStatus.OPEN,
            payable_id=None,
            void_reason=None,
            version=1,
        )

    @property
    def fingerprint(self) -> str:
        return f"M12:{self.company_id}:{self.origin}:{self.source_id}:v{self.source_version}"

    def convert(self, payable_id: UUID) -> ProvisionalFinancialEntry:
        if self.status is not ProvisionalEntryStatus.OPEN:
            raise InvalidProvisionalEntryError("only open provisional entries can be converted.")
        return replace(
            self,
            status=ProvisionalEntryStatus.CONVERTED,
            payable_id=_uuid(payable_id, "payable_id"),
            version=self.version + 1,
        )

    def void(self, reason: str) -> ProvisionalFinancialEntry:
        if self.status is not ProvisionalEntryStatus.OPEN:
            raise InvalidProvisionalEntryError("only open provisional entries can be voided.")
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason or len(normalized_reason) > 500:
            raise InvalidProvisionalEntryError(
                "void_reason must contain between 1 and 500 characters."
            )
        return replace(
            self,
            status=ProvisionalEntryStatus.VOIDED,
            void_reason=normalized_reason,
            version=self.version + 1,
        )

    def _validate_state_metadata(self) -> None:
        if self.status is ProvisionalEntryStatus.OPEN:
            if self.payable_id is not None or self.void_reason is not None:
                raise InvalidProvisionalEntryError(
                    "open provisional entries cannot contain terminal metadata."
                )
        elif self.status is ProvisionalEntryStatus.CONVERTED:
            if self.payable_id is None:
                raise InvalidProvisionalEntryError(
                    "converted provisional entries require payable_id."
                )
            _uuid(self.payable_id, "payable_id")
            if self.void_reason is not None:
                raise InvalidProvisionalEntryError(
                    "converted provisional entries cannot contain void_reason."
                )
        else:
            if self.payable_id is not None:
                raise InvalidProvisionalEntryError(
                    "voided provisional entries cannot contain payable_id."
                )
            normalized_reason = (
                self.void_reason.strip() if isinstance(self.void_reason, str) else ""
            )
            if not normalized_reason or len(normalized_reason) > 500:
                raise InvalidProvisionalEntryError(
                    "voided provisional entries require a valid void_reason."
                )
            object.__setattr__(self, "void_reason", normalized_reason)


__all__ = [
    "ProvisionalEntryOrigin",
    "ProvisionalEntryStatus",
    "ProvisionalFinancialEntry",
]
