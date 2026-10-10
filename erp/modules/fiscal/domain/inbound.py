"""Pure inbound NF-e and recipient-manifestation domain objects."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.fiscal.domain.access_key import NFeAccessKey
from erp.modules.fiscal.domain.document import FiscalDocumentModel
from erp.modules.fiscal.domain.exceptions import (
    InvalidInboundFiscalDocumentError,
    InvalidManifestationError,
)


class RecipientManifestationType(StrEnum):
    CONFIRMATION = "210200"
    ACKNOWLEDGEMENT = "210210"
    UNKNOWN_OPERATION = "210220"
    OPERATION_NOT_PERFORMED = "210240"

    @property
    def is_conclusive(self) -> bool:
        return self is not RecipientManifestationType.ACKNOWLEDGEMENT


class RecipientManifestationStatus(StrEnum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    OPERATION_NOT_PERFORMED = "OPERATION_NOT_PERFORMED"


@dataclass(frozen=True, slots=True)
class InboundFiscalParty:
    tax_id: str
    legal_name: str
    state_code: str

    def __post_init__(self) -> None:
        tax_id = "".join(character for character in self.tax_id if character.isdigit())
        name = self.legal_name.strip()
        state = self.state_code.strip().upper()
        if len(tax_id) not in {11, 14} or not name or len(state) != 2 or not state.isalpha():
            raise InvalidInboundFiscalDocumentError("Invalid inbound fiscal party snapshot.")
        object.__setattr__(self, "tax_id", tax_id)
        object.__setattr__(self, "legal_name", name)
        object.__setattr__(self, "state_code", state)


@dataclass(frozen=True, slots=True)
class InboundFiscalItem:
    line_number: int
    supplier_code: str
    description: str
    ncm: str
    cfop: str
    unit_of_measure: str
    quantity: Decimal
    unit_price: Decimal
    total_amount: Decimal

    def __post_init__(self) -> None:
        if self.line_number < 1:
            raise InvalidInboundFiscalDocumentError("Inbound line number must be positive.")
        if not all(
            value.strip()
            for value in (
                self.supplier_code,
                self.description,
                self.ncm,
                self.cfop,
                self.unit_of_measure,
            )
        ):
            raise InvalidInboundFiscalDocumentError("Inbound item identifiers are required.")
        if (
            any(
                not value.is_finite() or value < 0
                for value in (self.quantity, self.unit_price, self.total_amount)
            )
            or self.quantity == 0
        ):
            raise InvalidInboundFiscalDocumentError("Inbound item amounts are invalid.")


@dataclass(frozen=True, slots=True)
class RecipientManifestation:
    event_type: RecipientManifestationType
    sequence: int
    registered_at: datetime
    protocol: str
    status_code: str
    reason: str | None = None
    event_xml: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1 or not self.protocol.strip() or not self.status_code.strip():
            raise InvalidManifestationError(
                "Registered manifestation requires sequence and protocol."
            )


@dataclass(frozen=True, slots=True)
class InboundFiscalDocument:
    id: UUID
    company_id: UUID
    access_key: NFeAccessKey
    model: FiscalDocumentModel
    series: int
    number: int
    issued_at: datetime
    authorization_protocol: str
    supplier: InboundFiscalParty
    recipient: InboundFiscalParty
    items: tuple[InboundFiscalItem, ...]
    products_amount: Decimal
    total_amount: Decimal
    source_xml: str
    manifestations: tuple[RecipientManifestation, ...] = ()
    version: int = 1

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        access_key: NFeAccessKey,
        model: FiscalDocumentModel,
        series: int,
        number: int,
        issued_at: datetime,
        authorization_protocol: str,
        supplier: InboundFiscalParty,
        recipient: InboundFiscalParty,
        items: tuple[InboundFiscalItem, ...],
        products_amount: Decimal,
        total_amount: Decimal,
        source_xml: str,
        document_id: UUID | None = None,
    ) -> InboundFiscalDocument:
        if not isinstance(company_id, UUID) or not items or series < 1 or number < 1:
            raise InvalidInboundFiscalDocumentError("Invalid inbound document identity.")
        if (
            model is not FiscalDocumentModel.NFE
            or access_key.model != model.value
            or not authorization_protocol.strip()
        ):
            raise InvalidInboundFiscalDocumentError("Inbound NF-e key or protocol is inconsistent.")
        if issued_at.tzinfo is None or any(
            not value.is_finite() or value < 0 for value in (products_amount, total_amount)
        ):
            raise InvalidInboundFiscalDocumentError("Inbound issue date or total is invalid.")
        item_total = sum((item.total_amount for item in items), start=Decimal("0"))
        if abs(item_total - products_amount) > Decimal("0.01"):
            raise InvalidInboundFiscalDocumentError(
                "Inbound item total differs from document total by more than one cent."
            )
        xml = source_xml.strip()
        if not xml:
            raise InvalidInboundFiscalDocumentError("Inbound source XML is required.")
        return cls(
            id=document_id or uuid4(),
            company_id=company_id,
            access_key=access_key,
            model=model,
            series=series,
            number=number,
            issued_at=issued_at,
            authorization_protocol=authorization_protocol.strip(),
            supplier=supplier,
            recipient=recipient,
            items=items,
            products_amount=products_amount,
            total_amount=total_amount,
            source_xml=xml,
        )

    @property
    def conclusive_manifestation(self) -> RecipientManifestation | None:
        return next(
            (event for event in self.manifestations if event.event_type.is_conclusive), None
        )

    @property
    def manifestation_status(self) -> RecipientManifestationStatus:
        event = self.manifestations[-1] if self.manifestations else None
        if event is None:
            return RecipientManifestationStatus.PENDING
        return {
            RecipientManifestationType.ACKNOWLEDGEMENT: RecipientManifestationStatus.ACKNOWLEDGED,
            RecipientManifestationType.CONFIRMATION: RecipientManifestationStatus.CONFIRMED,
            RecipientManifestationType.UNKNOWN_OPERATION: RecipientManifestationStatus.UNKNOWN_OPERATION,
            RecipientManifestationType.OPERATION_NOT_PERFORMED: RecipientManifestationStatus.OPERATION_NOT_PERFORMED,
        }[event.event_type]

    def next_manifestation_sequence(
        self, event_type: RecipientManifestationType, reason: str | None = None
    ) -> int:
        if self.conclusive_manifestation is not None:
            raise InvalidManifestationError("A conclusive recipient manifestation is immutable.")
        if any(event.event_type is event_type for event in self.manifestations):
            raise InvalidManifestationError("Recipient manifestation was already registered.")
        normalized_reason = None if reason is None else reason.strip()
        if event_type is RecipientManifestationType.OPERATION_NOT_PERFORMED:
            if normalized_reason is None or len(normalized_reason) < 15:
                raise InvalidManifestationError(
                    "Operation not performed requires a reason of at least 15 characters."
                )
        elif normalized_reason is not None:
            raise InvalidManifestationError("Reason is only allowed for operation not performed.")
        return len(self.manifestations) + 1

    def register_manifestation(
        self, manifestation: RecipientManifestation
    ) -> InboundFiscalDocument:
        expected = self.next_manifestation_sequence(manifestation.event_type, manifestation.reason)
        if manifestation.sequence != expected:
            raise InvalidManifestationError("Manifestation sequence is not the expected value.")
        return replace(
            self,
            manifestations=(*self.manifestations, manifestation),
            version=self.version + 1,
        )


__all__ = [
    "InboundFiscalDocument",
    "InboundFiscalItem",
    "InboundFiscalParty",
    "RecipientManifestation",
    "RecipientManifestationStatus",
    "RecipientManifestationType",
]
