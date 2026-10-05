"""Tenant-bound persistence adapter for the M11 FiscalDocument aggregate."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentConflictError,
    FiscalDocumentItem,
    FiscalDocumentStatus,
    FiscalDocumentTotals,
    FiscalPartySnapshot,
    FiscalScopeError,
    FiscalVersionConflictError,
    NFeAccessKey,
    SefazResponseSnapshot,
    TaxComponentSnapshot,
    TaxKind,
    TaxSnapshot,
)
from erp.modules.fiscal.domain import (
    FiscalDocumentModel as DomainFiscalDocumentModel,
)
from erp.modules.fiscal.infrastructure.fiscal_document_model import (
    FiscalDocumentItemModel,
    FiscalDocumentModel,
)


class FiscalDocumentRepository:
    """Persist fiscal documents without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, document: FiscalDocument, *, actor_id: UUID) -> None:
        self._write_scope(document, actor_id)
        if document.version != 1 or document.status is not FiscalDocumentStatus.DRAFT:
            raise ValueError("A new fiscal document must start draft at version one.")
        self._session.add(_root_model(document, actor_id))
        await self._flush()
        self._session.add_all(_item_models(document, actor_id))
        await self._flush()

    async def get(self, document_id: UUID) -> FiscalDocument | None:
        root = await self._session.scalar(
            select(FiscalDocumentModel)
            .where(
                FiscalDocumentModel.company_id == self._company_id,
                FiscalDocumentModel.id == document_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _document(root, await self._items(document_id))

    async def list(
        self,
        *,
        status: FiscalDocumentStatus | None = None,
        access_key: str | None = None,
        model: DomainFiscalDocumentModel | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[FiscalDocument, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        statement = select(FiscalDocumentModel).where(
            FiscalDocumentModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, FiscalDocumentStatus):
                raise ValueError("status must be an official fiscal document status.")
            statement = statement.where(FiscalDocumentModel.status == status)
        if access_key is not None:
            statement = statement.where(FiscalDocumentModel.access_key == access_key)
        if model is not None:
            statement = statement.where(FiscalDocumentModel.model == model.value)
        if created_from is not None:
            statement = statement.where(FiscalDocumentModel.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(FiscalDocumentModel.created_at <= created_to)
        roots = await self._session.scalars(
            statement.order_by(
                FiscalDocumentModel.series,
                FiscalDocumentModel.number,
                FiscalDocumentModel.id,
            )
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        documents = []
        for root in roots:
            documents.append(_document(root, await self._items(root.id)))
        return tuple(documents)

    async def save(
        self,
        document: FiscalDocument,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> FiscalDocument:
        self._write_scope(document, actor_id)
        compare = document.version - 1 if expected_version is None else expected_version
        if compare < 1 or document.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        try:
            updated = cast(
                CursorResult[Any],
                await self._session.execute(
                    update(FiscalDocumentModel)
                    .where(
                        FiscalDocumentModel.company_id == self._company_id,
                        FiscalDocumentModel.id == document.id,
                        FiscalDocumentModel.version == compare,
                        FiscalDocumentModel.model == document.model,
                        FiscalDocumentModel.series == document.series,
                        FiscalDocumentModel.number == document.number,
                    )
                    .values(**_root_values(document, actor_id)),
                ),
            )
            if updated.rowcount != 1:
                raise FiscalVersionConflictError(
                    f"Fiscal document expected version {compare} is stale."
                )
            await self._session.execute(
                delete(FiscalDocumentItemModel).where(
                    FiscalDocumentItemModel.company_id == self._company_id,
                    FiscalDocumentItemModel.fiscal_document_id == document.id,
                )
            )
            self._session.add_all(_item_models(document, actor_id))
            await self._flush()
        except IntegrityError as error:
            self._translate(error)
        return document

    async def _items(self, document_id: UUID) -> tuple[FiscalDocumentItemModel, ...]:
        values = await self._session.scalars(
            select(FiscalDocumentItemModel)
            .where(
                FiscalDocumentItemModel.company_id == self._company_id,
                FiscalDocumentItemModel.fiscal_document_id == document_id,
            )
            .order_by(FiscalDocumentItemModel.line_number)
        )
        return tuple(values)

    def _write_scope(self, document: FiscalDocument, actor_id: UUID) -> None:
        if document.company_id != self._company_id:
            raise FiscalScopeError("Fiscal document is outside the selected company.")
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            self._translate(error)

    @staticmethod
    def _translate(error: IntegrityError) -> None:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise FiscalDocumentConflictError(
                "Fiscal access key or company series/number already exists."
            ) from error
        raise error


def _root_model(document: FiscalDocument, actor_id: UUID) -> FiscalDocumentModel:
    return FiscalDocumentModel(
        id=document.id,
        company_id=document.company_id,
        created_by=actor_id,
        **_root_values(document, actor_id),
    )


def _root_values(document: FiscalDocument, actor_id: UUID) -> dict[str, Any]:
    return {
        "model": document.model.value,
        "series": document.series,
        "number": document.number,
        "status": document.status.value,
        "issuer_snapshot": _party_payload(document.issuer),
        "recipient_snapshot": _party_payload(document.recipient),
        "products_amount": document.totals.products_amount,
        "freight_amount": document.totals.freight_amount,
        "discount_amount": document.totals.discount_amount,
        "tax_amount": document.totals.tax_amount,
        "total_amount": document.totals.total_amount,
        "access_key": None if document.access_key is None else str(document.access_key),
        "authorization_protocol": document.authorization_protocol,
        "rejection_code": document.rejection_code,
        "rejection_reason": document.rejection_reason,
        "authorized_at": document.authorized_at,
        "cancellation_protocol": document.cancellation_protocol,
        "cancelled_at": document.cancelled_at,
        "sefaz_history": [_sefaz_payload(value) for value in document.sefaz_history],
        "version": document.version,
        "updated_at": datetime.now(UTC),
        "updated_by": actor_id,
    }


def _item_models(document: FiscalDocument, actor_id: UUID) -> list[FiscalDocumentItemModel]:
    return [
        FiscalDocumentItemModel(
            id=item.id,
            company_id=document.company_id,
            fiscal_document_id=document.id,
            line_number=line_number,
            product_id=item.product_id,
            code=item.code,
            description=item.description,
            ncm=item.ncm,
            cfop=item.cfop,
            unit_of_measure=item.unit_of_measure,
            quantity=item.quantity,
            unit_price=item.unit_price,
            freight_amount=item.freight_amount,
            discount_amount=item.discount_amount,
            total_amount=item.total_amount,
            tax_snapshot=_tax_payload(item.tax_snapshot),
            created_by=actor_id,
            updated_by=actor_id,
        )
        for line_number, item in enumerate(document.items, start=1)
    ]


def _document(
    root: FiscalDocumentModel, items: tuple[FiscalDocumentItemModel, ...]
) -> FiscalDocument:
    return FiscalDocument(
        id=root.id,
        company_id=root.company_id,
        model=DomainFiscalDocumentModel(root.model),
        series=root.series,
        number=root.number,
        issuer=_party(root.issuer_snapshot),
        recipient=_party(root.recipient_snapshot),
        items=tuple(_item(value) for value in items),
        totals=FiscalDocumentTotals(
            products_amount=root.products_amount,
            freight_amount=root.freight_amount,
            discount_amount=root.discount_amount,
            tax_amount=root.tax_amount,
            total_amount=root.total_amount,
        ),
        status=FiscalDocumentStatus(root.status),
        version=root.version,
        access_key=None if root.access_key is None else NFeAccessKey(root.access_key),
        authorization_protocol=root.authorization_protocol,
        rejection_code=root.rejection_code,
        rejection_reason=root.rejection_reason,
        authorized_at=root.authorized_at,
        cancellation_protocol=root.cancellation_protocol,
        cancelled_at=root.cancelled_at,
        sefaz_history=tuple(_sefaz(value) for value in root.sefaz_history),
    )


def _item(model: FiscalDocumentItemModel) -> FiscalDocumentItem:
    return FiscalDocumentItem(
        id=model.id,
        product_id=model.product_id,
        code=model.code,
        description=model.description,
        ncm=model.ncm,
        cfop=model.cfop,
        unit_of_measure=model.unit_of_measure,
        quantity=model.quantity,
        unit_price=model.unit_price,
        freight_amount=model.freight_amount,
        discount_amount=model.discount_amount,
        total_amount=model.total_amount,
        tax_snapshot=_tax(model.tax_snapshot),
    )


def _party_payload(value: FiscalPartySnapshot) -> dict[str, Any]:
    return {
        "tax_id": value.tax_id,
        "legal_name": value.legal_name,
        "state_registration": value.state_registration,
        "street": value.street,
        "number": value.number,
        "district": value.district,
        "city": value.city,
        "state_code": value.state_code,
        "postal_code": value.postal_code,
        "country_code": value.country_code,
    }


def _party(value: dict[str, Any]) -> FiscalPartySnapshot:
    return FiscalPartySnapshot(**value)


def _tax_payload(value: TaxSnapshot) -> dict[str, Any]:
    return {
        kind.value.lower(): {
            "kind": component.kind.value,
            "tax_code": component.tax_code,
            "taxable_base": str(component.taxable_base),
            "rate": str(component.rate),
            "amount": str(component.amount),
        }
        for kind, component in (
            (TaxKind.ICMS, value.icms),
            (TaxKind.PIS, value.pis),
            (TaxKind.COFINS, value.cofins),
            (TaxKind.IPI, value.ipi),
        )
    }


def _tax(value: dict[str, Any]) -> TaxSnapshot:
    def component(name: str) -> TaxComponentSnapshot:
        payload = value[name]
        return TaxComponentSnapshot(
            kind=TaxKind(payload["kind"]),
            tax_code=str(payload["tax_code"]),
            taxable_base=Decimal(str(payload["taxable_base"])),
            rate=Decimal(str(payload["rate"])),
            amount=Decimal(str(payload["amount"])),
        )

    return TaxSnapshot(
        icms=component("icms"),
        pis=component("pis"),
        cofins=component("cofins"),
        ipi=component("ipi"),
    )


def _sefaz_payload(value: SefazResponseSnapshot) -> dict[str, Any]:
    return {
        "attempt_id": str(value.attempt_id),
        "status_code": value.status_code,
        "message": value.message,
        "occurred_at": value.occurred_at.isoformat(),
        "protocol": value.protocol,
    }


def _sefaz(value: dict[str, Any]) -> SefazResponseSnapshot:
    return SefazResponseSnapshot(
        attempt_id=UUID(str(value["attempt_id"])),
        status_code=str(value["status_code"]),
        message=str(value["message"]),
        occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
        protocol=None if value.get("protocol") is None else str(value["protocol"]),
    )


__all__ = ["FiscalDocumentRepository", "_document", "_item"]
