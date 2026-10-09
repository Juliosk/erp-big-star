"""Framework-free contracts for communication with SEFAZ authorizers."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from erp.modules.fiscal.domain import (
    FiscalAuthorizationStatus,
    FiscalDocumentModel,
    NFeAccessKey,
    RecipientManifestationType,
)


class SefazEnvironment(StrEnum):
    PRODUCTION = "PRODUCTION"
    HOMOLOGATION = "HOMOLOGATION"


class SefazSubmissionMode(StrEnum):
    SYNCHRONOUS = "SYNCHRONOUS"
    ASYNCHRONOUS = "ASYNCHRONOUS"


class ContingencyMode(StrEnum):
    NONE = "NONE"
    SVC_AN = "SVC_AN"
    SVC_RS = "SVC_RS"
    OFFLINE_NFCE = "OFFLINE_NFCE"


@dataclass(frozen=True, slots=True)
class SefazEndpoint:
    state_code: str
    environment: SefazEnvironment
    contingency: ContingencyMode = ContingencyMode.NONE

    def __post_init__(self) -> None:
        state = self.state_code.strip().upper()
        if len(state) != 2 or not state.isalpha():
            raise ValueError("SEFAZ state code must contain two letters.")
        object.__setattr__(self, "state_code", state)


@dataclass(frozen=True, slots=True)
class SefazServiceStatus:
    available: bool
    status_code: str
    message: str
    checked_at: datetime
    endpoint: SefazEndpoint


@dataclass(frozen=True, slots=True)
class SefazBatchRequest:
    batch_id: str
    signed_documents: tuple[bytes, ...]
    access_key: NFeAccessKey
    model: FiscalDocumentModel
    mode: SefazSubmissionMode
    endpoint: SefazEndpoint

    def __post_init__(self) -> None:
        if not self.batch_id.strip() or not self.signed_documents:
            raise ValueError("SEFAZ batch ID and signed documents are required.")


@dataclass(frozen=True, slots=True)
class SefazSubmissionResult:
    status: FiscalAuthorizationStatus
    status_code: str
    message: str
    endpoint: SefazEndpoint
    batch_id: str
    receipt_number: str | None = None
    protocol: str | None = None
    access_key: NFeAccessKey | None = None
    authorized_at: datetime | None = None
    authorized_xml: str | None = None


@dataclass(frozen=True, slots=True)
class SefazProtocolResult:
    status: FiscalAuthorizationStatus
    status_code: str
    message: str
    endpoint: SefazEndpoint
    receipt_number: str
    protocol: str | None = None
    access_key: NFeAccessKey | None = None
    authorized_at: datetime | None = None
    authorized_xml: str | None = None


@dataclass(frozen=True, slots=True)
class SefazCancellationRequest:
    access_key: NFeAccessKey
    authorization_protocol: str
    reason: str
    event_sequence: int
    endpoint: SefazEndpoint

    def __post_init__(self) -> None:
        if not self.authorization_protocol.strip() or len(self.reason.strip()) < 15:
            raise ValueError(
                "Cancellation protocol and a reason of at least 15 characters are required."
            )
        if self.event_sequence < 1:
            raise ValueError("Cancellation event sequence must be positive.")


@dataclass(frozen=True, slots=True)
class SefazCancellationResult:
    accepted: bool
    status_code: str
    message: str
    endpoint: SefazEndpoint
    protocol: str | None = None
    cancelled_at: datetime | None = None
    event_xml: str | None = None


@dataclass(frozen=True, slots=True)
class SefazManifestationRequest:
    access_key: NFeAccessKey
    event_type: RecipientManifestationType
    event_sequence: int
    endpoint: SefazEndpoint
    recipient_tax_id: str
    reason: str | None = None

    def __post_init__(self) -> None:
        tax_id = "".join(character for character in self.recipient_tax_id if character.isdigit())
        if (
            self.access_key.model != FiscalDocumentModel.NFE.value
            or len(tax_id) not in {11, 14}
            or self.event_sequence < 1
        ):
            raise ValueError("MDE recipient and event sequence are invalid.")
        reason = None if self.reason is None else self.reason.strip()
        if self.event_type is RecipientManifestationType.OPERATION_NOT_PERFORMED:
            if reason is None or len(reason) < 15:
                raise ValueError(
                    "Operation not performed requires a reason of at least 15 characters."
                )
        elif reason is not None:
            raise ValueError("MDE reason is only allowed for operation not performed.")
        object.__setattr__(self, "recipient_tax_id", tax_id)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class SefazManifestationResult:
    accepted: bool
    status_code: str
    message: str
    endpoint: SefazEndpoint
    protocol: str | None = None
    registered_at: datetime | None = None
    event_xml: str | None = None


class SefazGatewayPort(Protocol):
    async def service_status(self, endpoint: SefazEndpoint) -> SefazServiceStatus: ...

    async def sign_xml(self, xml: bytes, *, reference_uri: str) -> bytes: ...

    async def submit_batch(self, request: SefazBatchRequest) -> SefazSubmissionResult: ...

    async def query_protocol(
        self, endpoint: SefazEndpoint, receipt_number: str
    ) -> SefazProtocolResult: ...

    async def cancel_document(
        self, request: SefazCancellationRequest
    ) -> SefazCancellationResult: ...

    async def manifest_recipient(
        self, request: SefazManifestationRequest
    ) -> SefazManifestationResult: ...


__all__ = [
    "ContingencyMode",
    "SefazBatchRequest",
    "SefazCancellationRequest",
    "SefazCancellationResult",
    "SefazEndpoint",
    "SefazEnvironment",
    "SefazGatewayPort",
    "SefazManifestationRequest",
    "SefazManifestationResult",
    "SefazProtocolResult",
    "SefazServiceStatus",
    "SefazSubmissionMode",
    "SefazSubmissionResult",
]
