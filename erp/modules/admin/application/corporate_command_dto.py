"""Inputs and replayable outputs for corporate creation commands."""

from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

from erp.modules.admin.application.corporate_dto import CompanyView
from erp.modules.admin.domain import Branch, CorporateStatus


@dataclass(frozen=True, slots=True)
class RequestMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None


@dataclass(frozen=True, slots=True)
class CreateCompanyCommand:
    group_id: UUID
    code: str
    legal_name: str
    trade_name: str | None
    tax_id: str
    timezone: str
    idempotency_key: str
    metadata: RequestMetadata

    def idempotency_payload(self) -> dict[str, object]:
        return {
            "group_id": str(self.group_id),
            "code": self.code,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "tax_id": self.tax_id,
            "timezone": self.timezone,
        }


@dataclass(frozen=True, slots=True)
class CreateBranchCommand:
    company_id: UUID
    code: str
    name: str
    tax_id: str
    timezone: str
    idempotency_key: str
    metadata: RequestMetadata

    def idempotency_payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "code": self.code,
            "name": self.name,
            "tax_id": self.tax_id,
            "timezone": self.timezone,
        }


@dataclass(frozen=True, slots=True)
class CompanyCreationResult:
    company: CompanyView
    event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "company": _company_dict(self.company),
            "event_id": str(self.event_id),
            "audit_event_id": str(self.audit_event_id),
            "idempotency_replayed": False,
        }

    @classmethod
    def from_replay(cls, payload: dict[str, Any]) -> Self:
        company = _company_from_dict(_mapping(payload, "company"))
        return cls(
            company=company,
            event_id=UUID(str(payload["event_id"])),
            audit_event_id=UUID(str(payload["audit_event_id"])),
            idempotency_replayed=True,
        )


@dataclass(frozen=True, slots=True)
class BranchView:
    id: UUID
    company_id: UUID
    code: str
    name: str
    tax_id: str
    timezone: str
    status: CorporateStatus
    version: int

    @classmethod
    def from_domain(cls, branch: Branch) -> Self:
        return cls(
            id=branch.id,
            company_id=branch.company_id,
            code=branch.code,
            name=branch.name,
            tax_id=str(branch.tax_id),
            timezone=branch.timezone,
            status=branch.status,
            version=branch.version,
        )


@dataclass(frozen=True, slots=True)
class BranchCreationResult:
    branch: BranchView
    event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": _branch_dict(self.branch),
            "event_id": str(self.event_id),
            "audit_event_id": str(self.audit_event_id),
            "idempotency_replayed": False,
        }

    @classmethod
    def from_replay(cls, payload: dict[str, Any]) -> Self:
        branch = _branch_from_dict(_mapping(payload, "branch"))
        return cls(
            branch=branch,
            event_id=UUID(str(payload["event_id"])),
            audit_event_id=UUID(str(payload["audit_event_id"])),
            idempotency_replayed=True,
        )


def _company_dict(company: CompanyView) -> dict[str, object]:
    return {
        "id": str(company.id),
        "group_id": str(company.group_id),
        "code": company.code,
        "legal_name": company.legal_name,
        "trade_name": company.trade_name,
        "tax_id": company.tax_id,
        "timezone": company.timezone,
        "status": company.status,
        "version": company.version,
    }


def _company_from_dict(payload: dict[str, Any]) -> CompanyView:
    trade_name = payload.get("trade_name")
    return CompanyView(
        id=UUID(str(payload["id"])),
        group_id=UUID(str(payload["group_id"])),
        code=str(payload["code"]),
        legal_name=str(payload["legal_name"]),
        trade_name=None if trade_name is None else str(trade_name),
        tax_id=str(payload["tax_id"]),
        timezone=str(payload["timezone"]),
        status=CorporateStatus(str(payload["status"])),
        version=int(payload["version"]),
    )


def _branch_dict(branch: BranchView) -> dict[str, object]:
    return {
        "id": str(branch.id),
        "company_id": str(branch.company_id),
        "code": branch.code,
        "name": branch.name,
        "tax_id": branch.tax_id,
        "timezone": branch.timezone,
        "status": branch.status,
        "version": branch.version,
    }


def _branch_from_dict(payload: dict[str, Any]) -> BranchView:
    return BranchView(
        id=UUID(str(payload["id"])),
        company_id=UUID(str(payload["company_id"])),
        code=str(payload["code"]),
        name=str(payload["name"]),
        tax_id=str(payload["tax_id"]),
        timezone=str(payload["timezone"]),
        status=CorporateStatus(str(payload["status"])),
        version=int(payload["version"]),
    )


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Stored idempotency response has invalid {key} data.")
    return value


__all__ = [
    "BranchCreationResult",
    "BranchView",
    "CompanyCreationResult",
    "CreateBranchCommand",
    "CreateCompanyCommand",
    "RequestMetadata",
]
