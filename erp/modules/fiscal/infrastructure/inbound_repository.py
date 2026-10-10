"""Tenant-bound repository for inbound fiscal documents and MDE history."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.fiscal.domain import (
    FiscalDocumentConflictError,
    FiscalDocumentModel,
    FiscalScopeError,
    FiscalVersionConflictError,
    InboundFiscalDocument,
    InboundFiscalItem,
    InboundFiscalParty,
    NFeAccessKey,
    RecipientManifestation,
    RecipientManifestationStatus,
    RecipientManifestationType,
)
from erp.modules.fiscal.infrastructure.inbound_model import (
    InboundFiscalDocumentItemModel,
    InboundFiscalDocumentModel,
    MdeEventModel,
)


class InboundFiscalDocumentRepository:
    """Maps the aggregate without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, document: InboundFiscalDocument, *, actor_id: UUID) -> None:
        self._write_scope(document, actor_id)
        if document.version != 1 or document.manifestations:
            raise ValueError("A new inbound document must start at version one without MDE events.")
        self._session.add(_root_model(document, actor_id))
        await self._flush()
        self._session.add_all(_item_models(document, actor_id))
        await self._flush()

    async def get(self, document_id: UUID) -> InboundFiscalDocument | None:
        root = await self._session.scalar(
            select(InboundFiscalDocumentModel)
            .where(
                InboundFiscalDocumentModel.company_id == self._company_id,
                InboundFiscalDocumentModel.id == document_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _document(
            root,
            await self._items(document_id),
            await self._events(document_id),
        )

    async def get_by_access_key(self, access_key: str) -> InboundFiscalDocument | None:
        document_id = await self._session.scalar(
            select(InboundFiscalDocumentModel.id).where(
                InboundFiscalDocumentModel.company_id == self._company_id,
                InboundFiscalDocumentModel.access_key == access_key,
            )
        )
        return None if document_id is None else await self.get(document_id)

    async def list(
        self,
        *,
        access_key: str | None = None,
        supplier_tax_id: str | None = None,
        mde_status: RecipientManifestationStatus | None = None,
        issued_from: datetime | None = None,
        issued_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[InboundFiscalDocument, ...]:
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError("Invalid inbound document pagination.")
        statement = select(InboundFiscalDocumentModel).where(
            InboundFiscalDocumentModel.company_id == self._company_id
        )
        if access_key is not None:
            statement = statement.where(InboundFiscalDocumentModel.access_key == access_key)
        if supplier_tax_id is not None:
            statement = statement.where(
                InboundFiscalDocumentModel.supplier_tax_id == supplier_tax_id
            )
        if mde_status is not None:
            statement = statement.where(InboundFiscalDocumentModel.mde_status == mde_status.value)
        if issued_from is not None:
            statement = statement.where(InboundFiscalDocumentModel.issued_at >= issued_from)
        if issued_to is not None:
            statement = statement.where(InboundFiscalDocumentModel.issued_at <= issued_to)
        roots = await self._session.scalars(
            statement.order_by(
                InboundFiscalDocumentModel.issued_at.desc(),
                InboundFiscalDocumentModel.id,
            )
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        documents = []
        for root in roots:
            documents.append(
                _document(root, await self._items(root.id), await self._events(root.id))
            )
        return tuple(documents)

    async def save(
        self,
        document: InboundFiscalDocument,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> InboundFiscalDocument:
        self._write_scope(document, actor_id)
        if expected_version < 1 or document.version != expected_version + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(InboundFiscalDocumentModel)
                .where(
                    InboundFiscalDocumentModel.company_id == self._company_id,
                    InboundFiscalDocumentModel.id == document.id,
                    InboundFiscalDocumentModel.version == expected_version,
                )
                .values(
                    mde_status=document.manifestation_status.value,
                    version=document.version,
                    updated_at=datetime.now(UTC),
                    updated_by=actor_id,
                )
            ),
        )
        if updated.rowcount != 1:
            raise FiscalVersionConflictError(
                f"Inbound fiscal document expected version {expected_version} is stale."
            )
        persisted_count = await self._session.scalar(
            select(func.count())
            .select_from(MdeEventModel)
            .where(
                MdeEventModel.company_id == self._company_id,
                MdeEventModel.inbound_fiscal_document_id == document.id,
            )
        )
        start = int(persisted_count or 0)
        self._session.add_all(
            _event_model(document, event, actor_id) for event in document.manifestations[start:]
        )
        await self._flush()
        return document

    async def _items(self, document_id: UUID) -> tuple[InboundFiscalDocumentItemModel, ...]:
        result = await self._session.scalars(
            select(InboundFiscalDocumentItemModel)
            .where(
                InboundFiscalDocumentItemModel.company_id == self._company_id,
                InboundFiscalDocumentItemModel.inbound_fiscal_document_id == document_id,
            )
            .order_by(InboundFiscalDocumentItemModel.line_number)
        )
        return tuple(result)

    async def _events(self, document_id: UUID) -> tuple[MdeEventModel, ...]:
        result = await self._session.scalars(
            select(MdeEventModel)
            .where(
                MdeEventModel.company_id == self._company_id,
                MdeEventModel.inbound_fiscal_document_id == document_id,
            )
            .order_by(MdeEventModel.sequence)
        )
        return tuple(result)

    def _write_scope(self, document: InboundFiscalDocument, actor_id: UUID) -> None:
        if document.company_id != self._company_id:
            raise FiscalScopeError("Inbound fiscal document is outside the selected company.")
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise FiscalDocumentConflictError(
                    "Inbound fiscal access key or MDE event already exists."
                ) from error
            raise


def _root_model(document: InboundFiscalDocument, actor_id: UUID) -> InboundFiscalDocumentModel:
    return InboundFiscalDocumentModel(
        id=document.id,
        company_id=document.company_id,
        access_key=str(document.access_key),
        model=document.model.value,
        series=document.series,
        number=document.number,
        issued_at=document.issued_at,
        authorization_protocol=document.authorization_protocol,
        supplier_tax_id=document.supplier.tax_id,
        supplier_snapshot=_party_payload(document.supplier),
        recipient_snapshot=_party_payload(document.recipient),
        products_amount=document.products_amount,
        total_amount=document.total_amount,
        source_xml=document.source_xml,
        mde_status=document.manifestation_status.value,
        version=document.version,
        created_by=actor_id,
        updated_by=actor_id,
    )


def _item_models(
    document: InboundFiscalDocument, actor_id: UUID
) -> list[InboundFiscalDocumentItemModel]:
    return [
        InboundFiscalDocumentItemModel(
            id=uuid4(),
            company_id=document.company_id,
            inbound_fiscal_document_id=document.id,
            line_number=item.line_number,
            supplier_code=item.supplier_code,
            description=item.description,
            ncm=item.ncm,
            cfop=item.cfop,
            unit_of_measure=item.unit_of_measure,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_amount=item.total_amount,
            created_by=actor_id,
        )
        for item in document.items
    ]


def _event_model(
    document: InboundFiscalDocument,
    event: RecipientManifestation,
    actor_id: UUID,
) -> MdeEventModel:
    return MdeEventModel(
        id=uuid4(),
        company_id=document.company_id,
        inbound_fiscal_document_id=document.id,
        event_type=event.event_type.value,
        sequence=event.sequence,
        registered_at=event.registered_at,
        protocol=event.protocol,
        status_code=event.status_code,
        reason=event.reason,
        event_xml=event.event_xml,
        created_by=actor_id,
    )


def _document(
    root: InboundFiscalDocumentModel,
    items: tuple[InboundFiscalDocumentItemModel, ...],
    events: tuple[MdeEventModel, ...],
) -> InboundFiscalDocument:
    return InboundFiscalDocument(
        id=root.id,
        company_id=root.company_id,
        access_key=NFeAccessKey(root.access_key),
        model=FiscalDocumentModel(root.model),
        series=root.series,
        number=root.number,
        issued_at=root.issued_at,
        authorization_protocol=root.authorization_protocol,
        supplier=_party(root.supplier_snapshot),
        recipient=_party(root.recipient_snapshot),
        items=tuple(_item(value) for value in items),
        products_amount=root.products_amount,
        total_amount=root.total_amount,
        source_xml=root.source_xml,
        manifestations=tuple(_event(value) for value in events),
        version=root.version,
    )


def _party_payload(value: InboundFiscalParty) -> dict[str, str]:
    return {
        "tax_id": value.tax_id,
        "legal_name": value.legal_name,
        "state_code": value.state_code,
    }


def _party(value: dict[str, Any]) -> InboundFiscalParty:
    return InboundFiscalParty(
        tax_id=str(value["tax_id"]),
        legal_name=str(value["legal_name"]),
        state_code=str(value["state_code"]),
    )


def _item(value: InboundFiscalDocumentItemModel) -> InboundFiscalItem:
    return InboundFiscalItem(
        line_number=value.line_number,
        supplier_code=value.supplier_code,
        description=value.description,
        ncm=value.ncm,
        cfop=value.cfop,
        unit_of_measure=value.unit_of_measure,
        quantity=value.quantity,
        unit_price=value.unit_price,
        total_amount=value.total_amount,
    )


def _event(value: MdeEventModel) -> RecipientManifestation:
    return RecipientManifestation(
        event_type=RecipientManifestationType(value.event_type),
        sequence=value.sequence,
        registered_at=value.registered_at,
        protocol=value.protocol,
        status_code=value.status_code,
        reason=value.reason,
        event_xml=value.event_xml,
    )


__all__ = ["InboundFiscalDocumentRepository"]
