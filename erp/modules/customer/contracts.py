"""Explicit M14 integration surface; no persistence types are exported."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.customer.application.permissions import CUSTOMER_READ, CustomerAuthorization


@dataclass(frozen=True, slots=True)
class CustomerReference:
    customer_id: UUID
    company_id: UUID
    customer_type: str
    status: str
    identity_ref: str
    legal_name: str
    version: int


__all__ = ["CUSTOMER_READ", "CustomerAuthorization", "CustomerReference"]
