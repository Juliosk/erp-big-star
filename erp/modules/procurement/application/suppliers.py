"""Authorized M6 supplier use cases and framework-neutral contracts."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.application.permissions import (
    PROCUREMENT_SUPPLIER_MANAGE,
    PROCUREMENT_SUPPLIER_READ,
    ProcurementAuthorization,
)
from erp.modules.procurement.domain import (
    Supplier,
    SupplierAddress,
    SupplierIdentityKind,
    SupplierKind,
    SupplierSite,
    SupplierStatus,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class SupplierSiteInput:
    code: str
    name: str
    line1: str
    city: str
    country_code: str
    state: str | None = None
    postal_code: str | None = None
    line2: str | None = None
    district: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool = False


@dataclass(frozen=True, slots=True)
class CreateSupplier:
    company_id: UUID
    kind: SupplierKind
    identity_kind: SupplierIdentityKind
    identity_value: str
    identity_country_code: str
    legal_name: str
    trade_name: str | None = None
    sites: tuple[SupplierSiteInput, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateSupplier:
    company_id: UUID
    supplier_id: UUID
    expected_version: int
    legal_name: str | None = None
    trade_name: str | None = None
    clear_trade_name: bool = False
    status: SupplierStatus | None = None


@dataclass(frozen=True, slots=True)
class SupplierPage:
    items: tuple[Supplier, ...]
    page: int
    page_size: int
    has_more: bool


class SupplierStore(Protocol):
    async def create(self, supplier: Supplier, *, actor_id: UUID) -> Supplier: ...

    async def update(self, command: UpdateSupplier, *, actor_id: UUID) -> Supplier: ...

    async def get(self, company_id: UUID, supplier_id: UUID) -> Supplier | None: ...

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: SupplierStatus | None,
        document: str | None,
    ) -> SupplierPage: ...


def apply_supplier_update(supplier: Supplier, command: UpdateSupplier) -> Supplier:
    if supplier.version != command.expected_version:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The resource was changed by another transaction.",
            status_code=409,
        )
    if (
        command.legal_name is None
        and command.trade_name is None
        and not command.clear_trade_name
        and command.status is None
    ):
        raise ApplicationError(
            code="EMPTY_PATCH", message="At least one mutable field is required.", status_code=422
        )
    try:
        changed = supplier.update_master(
            legal_name=supplier.legal_name if command.legal_name is None else command.legal_name,
            trade_name=None
            if command.clear_trade_name
            else supplier.trade_name
            if command.trade_name is None
            else command.trade_name,
        )
        if command.status is not None:
            changed = changed.transition_status(command.status)
        return changed
    except ValueError as error:
        raise _validation_error(error) from error


class SupplierService:
    def __init__(self, store: SupplierStore, authorization: ProcurementAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(self, context: SecurityContext, command: CreateSupplier) -> Supplier:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_SUPPLIER_MANAGE, write=True
        )
        try:
            supplier = Supplier.create(
                company_id=command.company_id,
                kind=command.kind,
                identity_kind=command.identity_kind,
                identity_value=command.identity_value,
                identity_country_code=command.identity_country_code,
                legal_name=command.legal_name,
                trade_name=command.trade_name,
            )
            for item in command.sites:
                supplier = supplier.add_site(
                    SupplierSite.create(
                        company_id=supplier.company_id,
                        supplier_id=supplier.id,
                        code=item.code,
                        name=item.name,
                        address=SupplierAddress.create(
                            line1=item.line1,
                            city=item.city,
                            country_code=item.country_code,
                            state=item.state,
                            postal_code=item.postal_code,
                            line2=item.line2,
                            district=item.district,
                        ),
                        email=item.email,
                        phone=item.phone,
                        is_primary=item.is_primary,
                    )
                )
        except ValueError as error:
            raise _validation_error(error) from error
        return await self._store.create(supplier, actor_id=context.principal.user_id)

    async def update(self, context: SecurityContext, command: UpdateSupplier) -> Supplier:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_SUPPLIER_MANAGE, write=True
        )
        return await self._store.update(command, actor_id=context.principal.user_id)

    async def get(self, context: SecurityContext, company_id: UUID, supplier_id: UUID) -> Supplier:
        await self._authorization.require(context, company_id, PROCUREMENT_SUPPLIER_READ)
        supplier = await self._store.get(company_id, supplier_id)
        if supplier is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Supplier not found.", status_code=404
            )
        return supplier

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: SupplierStatus | None = None,
        document: str | None = None,
    ) -> SupplierPage:
        await self._authorization.require(context, company_id, PROCUREMENT_SUPPLIER_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
            )
        normalized_document = _document(document)
        return await self._store.list(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            document=normalized_document,
        )


def _document(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip().upper()
    if not trimmed:
        raise ApplicationError(
            code="VALIDATION_ERROR", message="Document filter cannot be empty.", status_code=422
        )
    if all(char.isdigit() or char in ".-/ " for char in trimmed):
        return "".join(char for char in trimmed if char.isdigit())
    return trimmed


def _validation_error(error: ValueError) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid supplier data.",
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = [
    "CreateSupplier",
    "SupplierPage",
    "SupplierService",
    "SupplierSiteInput",
    "SupplierStore",
    "UpdateSupplier",
    "apply_supplier_update",
]
