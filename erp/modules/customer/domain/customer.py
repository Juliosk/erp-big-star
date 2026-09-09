"""Company-owned customer golden record."""

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.customer.domain.tax_id import CustomerTaxId, TaxIdKind


class CustomerType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    COMPANY = "COMPANY"


class CustomerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Customer:
    """The M14 canonical customer record; marketplace identities are secondary."""

    id: UUID
    company_id: UUID
    customer_type: CustomerType
    tax_id: CustomerTaxId
    legal_name: str
    trade_name: str | None
    status: CustomerStatus
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise ValueError("Customer identity and company scope must be UUIDs.")
        if not isinstance(self.customer_type, CustomerType):
            raise ValueError("customer_type must be an official M14 type.")
        if not isinstance(self.tax_id, CustomerTaxId):
            raise ValueError("tax_id must be a validated customer identity.")
        if self.customer_type is CustomerType.INDIVIDUAL and self.tax_id.kind is not TaxIdKind.CPF:
            raise ValueError("INDIVIDUAL customers require CPF.")
        if self.customer_type is CustomerType.COMPANY and self.tax_id.kind is not TaxIdKind.CNPJ:
            raise ValueError("COMPANY customers require CNPJ.")
        if not 1 <= len(self.legal_name) <= 200 or self.legal_name != self.legal_name.strip():
            raise ValueError("legal_name must contain 1 to 200 trimmed characters.")
        if self.trade_name is not None and (
            not 1 <= len(self.trade_name) <= 200 or self.trade_name != self.trade_name.strip()
        ):
            raise ValueError("trade_name must contain 1 to 200 trimmed characters when present.")
        if not isinstance(self.status, CustomerStatus):
            raise ValueError("status must be an official M14 status.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @property
    def identity_type(self) -> TaxIdKind:
        return self.tax_id.kind

    @property
    def identity_value(self) -> str:
        return self.tax_id.value

    @property
    def identity_ref(self) -> str:
        return self.tax_id.reference

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        customer_type: CustomerType,
        identity_type: TaxIdKind,
        identity_value: str,
        legal_name: str,
        trade_name: str | None = None,
    ) -> Customer:
        """New customer masters start active at version one."""
        normalized_trade_name = trade_name.strip() if trade_name is not None else None
        return cls(
            id=uuid4(),
            company_id=company_id,
            customer_type=customer_type,
            tax_id=CustomerTaxId(identity_type, identity_value),
            legal_name=legal_name.strip(),
            trade_name=normalized_trade_name if trade_name is not None else None,
            status=CustomerStatus.ACTIVE,
            version=1,
        )

    def update_master(self, *, legal_name: str, trade_name: str | None) -> Customer:
        """Change non-identity master data."""
        normalized_trade_name = trade_name.strip() if trade_name is not None else None
        candidate = replace(
            self,
            legal_name=legal_name.strip(),
            trade_name=normalized_trade_name if trade_name is not None else None,
        )
        if candidate == self:
            return self
        return replace(candidate, version=self.version + 1)

    def transition_status(self, target: CustomerStatus) -> Customer:
        """Apply an explicit operational-status transition."""
        if not isinstance(target, CustomerStatus):
            raise ValueError("target status must be an official M14 status.")
        if target is self.status:
            return self
        allowed = {
            CustomerStatus.ACTIVE: {CustomerStatus.INACTIVE, CustomerStatus.BLOCKED},
            CustomerStatus.INACTIVE: {CustomerStatus.ACTIVE, CustomerStatus.BLOCKED},
            CustomerStatus.BLOCKED: {CustomerStatus.ACTIVE},
        }
        if target not in allowed[self.status]:
            raise ValueError("The requested customer status transition is not allowed.")
        return replace(self, status=target, version=self.version + 1)


__all__ = ["Customer", "CustomerStatus", "CustomerType"]
