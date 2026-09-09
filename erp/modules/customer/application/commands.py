"""Technology-neutral customer commands and replayable command result."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from erp.modules.customer.domain import (
    Customer,
    CustomerStatus,
    CustomerTaxId,
    CustomerType,
    TaxIdKind,
)


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class CreateCustomer:
    company_id: UUID
    customer_type: CustomerType
    identity_type: TaxIdKind
    identity_value: str
    legal_name: str
    trade_name: str | None
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "customer_type": self.customer_type,
            "identity_type": self.identity_type,
            "identity_value": CustomerTaxId(self.identity_type, self.identity_value).value,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
        }


def customer_snapshot(customer: Customer) -> dict[str, object]:
    return {
        "id": str(customer.id),
        "company_id": str(customer.company_id),
        "customer_type": customer.customer_type,
        "identity_type": customer.tax_id.kind,
        "identity_value": customer.tax_id.value,
        "identity_ref": customer.tax_id.reference,
        "legal_name": customer.legal_name,
        "trade_name": customer.trade_name,
        "status": customer.status,
        "version": customer.version,
    }


@dataclass(frozen=True, slots=True)
class CustomerCommandResult:
    customer: Customer
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "customer": customer_snapshot(self.customer),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id) if self.audit_event_id is not None else None,
            "idempotency_replayed": self.idempotency_replayed,
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> CustomerCommandResult:
        item = body["customer"]
        return cls(
            customer=Customer(
                id=UUID(item["id"]),
                company_id=UUID(item["company_id"]),
                customer_type=CustomerType(item["customer_type"]),
                tax_id=CustomerTaxId(TaxIdKind(item["identity_type"]), item["identity_value"]),
                legal_name=item["legal_name"],
                trade_name=item["trade_name"],
                status=CustomerStatus(item["status"]),
                version=item["version"],
            ),
            event_id=UUID(body["event_id"]) if body["event_id"] is not None else None,
            audit_event_id=UUID(body["audit_event_id"])
            if body["audit_event_id"] is not None
            else None,
            idempotency_replayed=True,
        )


class CustomerCreationStore(Protocol):
    async def create(
        self, customer: Customer, command: CreateCustomer, actor_id: UUID
    ) -> CustomerCommandResult: ...


__all__ = [
    "CommandMetadata",
    "CreateCustomer",
    "CustomerCommandResult",
    "CustomerCreationStore",
    "customer_snapshot",
]
