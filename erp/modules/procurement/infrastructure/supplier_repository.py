"""Tenant-bound PostgreSQL repository for the M6 supplier aggregate."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.domain import (
    Supplier,
    SupplierAddress,
    SupplierIdentityKind,
    SupplierKind,
    SupplierSite,
    SupplierStatus,
    SupplierTaxIdentity,
)
from erp.modules.procurement.infrastructure.supplier_model import (
    SupplierModel,
    SupplierSiteModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


class SupplierConflictError(ApplicationError):
    """Stable M6 conflict raised for duplicate fiscal identities or site codes."""

    def __init__(self) -> None:
        super().__init__(
            code="SUPPLIER_CONFLICT",
            message="A supplier fiscal identity or site code already exists for this company.",
            status_code=409,
        )


def _site(model: SupplierSiteModel) -> SupplierSite:
    return SupplierSite(
        id=model.id,
        company_id=model.company_id,
        supplier_id=model.supplier_id,
        code=model.code,
        name=model.name,
        address=SupplierAddress(
            line1=model.line1,
            city=model.city,
            country_code=model.country_code,
            state=model.state,
            postal_code=model.postal_code,
            line2=model.line2,
            district=model.district,
        ),
        email=model.email,
        phone=model.phone,
        is_primary=model.is_primary,
        active=model.active,
    )


def _supplier(model: SupplierModel, sites: tuple[SupplierSiteModel, ...]) -> Supplier:
    return Supplier(
        id=model.id,
        company_id=model.company_id,
        kind=SupplierKind(model.kind),
        tax_identity=SupplierTaxIdentity(
            SupplierIdentityKind(model.identity_kind),
            model.identity_value,
            model.identity_country_code,
        ),
        legal_name=model.legal_name,
        trade_name=model.trade_name,
        status=SupplierStatus(model.status),
        sites=tuple(_site(site) for site in sites),
        version=model.version,
    )


class SupplierRepository:
    """Persist one company's suppliers without exposing an unscoped operation."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, supplier: Supplier, *, actor_id: UUID) -> None:
        """Flush a new supplier and all sites, leaving commit control to the caller."""
        self._validate_write(supplier, actor_id)
        if supplier.version != 1 or supplier.status is not SupplierStatus.ACTIVE:
            raise ValueError("A new supplier must start active at version one.")
        if supplier.sites:
            raise ValueError("A new version-one supplier cannot already contain sites.")
        self._session.add(
            SupplierModel(
                id=supplier.id,
                company_id=self._company_id,
                kind=supplier.kind,
                identity_kind=supplier.tax_identity.kind,
                identity_value=supplier.tax_identity.value,
                identity_country_code=supplier.tax_identity.country_code,
                legal_name=supplier.legal_name,
                trade_name=supplier.trade_name,
                status=supplier.status,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict()

    async def get(self, supplier_id: UUID) -> Supplier | None:
        """Return no data for missing suppliers or another company's supplier."""
        result = await self._session.scalars(
            select(SupplierModel)
            .where(
                SupplierModel.company_id == self._company_id,
                SupplierModel.id == supplier_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            return None
        return _supplier(model, await self._sites(supplier_id))

    async def list(
        self,
        *,
        status: SupplierStatus | None = None,
        kind: SupplierKind | None = None,
        identity_value: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Supplier, ...]:
        """Return a deterministic, bounded directory for the selected company."""
        self._validate_filters(status=status, kind=kind, limit=limit, offset=offset)
        statement = select(SupplierModel).where(SupplierModel.company_id == self._company_id)
        if status is not None:
            statement = statement.where(SupplierModel.status == status)
        if kind is not None:
            statement = statement.where(SupplierModel.kind == kind)
        if identity_value is not None:
            statement = statement.where(SupplierModel.identity_value == identity_value)
        models = await self._session.scalars(
            statement.order_by(SupplierModel.legal_name, SupplierModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        suppliers: list[Supplier] = []
        for model in models:
            suppliers.append(_supplier(model, await self._sites(model.id)))
        return tuple(suppliers)

    async def save(
        self,
        supplier: Supplier,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> Supplier:
        """Persist an aggregate change using a tenant-bound optimistic comparison."""
        self._validate_write(supplier, actor_id)
        compare_version = supplier.version - 1 if expected_version is None else expected_version
        if compare_version < 1 or supplier.version <= compare_version:
            raise ValueError("save requires an aggregate version newer than expected_version.")
        result = await self._session.scalars(
            update(SupplierModel)
            .where(
                SupplierModel.company_id == self._company_id,
                SupplierModel.id == supplier.id,
                SupplierModel.version == compare_version,
                SupplierModel.kind == supplier.kind,
                SupplierModel.identity_kind == supplier.tax_identity.kind,
                SupplierModel.identity_value == supplier.tax_identity.value,
                SupplierModel.identity_country_code == supplier.tax_identity.country_code,
            )
            .values(
                legal_name=supplier.legal_name,
                trade_name=supplier.trade_name,
                status=supplier.status,
                version=supplier.version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(SupplierModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=compare_version)
        await self._save_sites(supplier, actor_id=actor_id)
        await self._flush_conflict()
        return _supplier(model, await self._sites(supplier.id))

    async def _sites(self, supplier_id: UUID) -> tuple[SupplierSiteModel, ...]:
        result = await self._session.scalars(
            select(SupplierSiteModel)
            .where(
                SupplierSiteModel.company_id == self._company_id,
                SupplierSiteModel.supplier_id == supplier_id,
            )
            .order_by(SupplierSiteModel.code, SupplierSiteModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(result)

    async def _save_sites(self, supplier: Supplier, *, actor_id: UUID) -> None:
        existing = {site.id: site for site in await self._sites(supplier.id)}
        for site in supplier.sites:
            model = existing.get(site.id)
            values = self._site_values(site)
            if model is None:
                self._session.add(
                    SupplierSiteModel(
                        id=site.id,
                        company_id=self._company_id,
                        supplier_id=supplier.id,
                        **values,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
            else:
                await self._session.execute(
                    update(SupplierSiteModel)
                    .where(
                        SupplierSiteModel.company_id == self._company_id,
                        SupplierSiteModel.supplier_id == supplier.id,
                        SupplierSiteModel.id == site.id,
                    )
                    .values(**values, updated_at=datetime.now(UTC), updated_by=actor_id)
                    .execution_options(synchronize_session=False)
                )

    @staticmethod
    def _site_values(site: SupplierSite) -> dict[str, object]:
        return {
            "code": site.code,
            "name": site.name,
            "line1": site.address.line1,
            "line2": site.address.line2,
            "district": site.address.district,
            "city": site.address.city,
            "state": site.address.state,
            "postal_code": site.address.postal_code,
            "country_code": site.address.country_code,
            "email": site.email,
            "phone": site.phone,
            "is_primary": site.is_primary,
            "active": site.active,
        }

    def _validate_write(self, supplier: Supplier, actor_id: UUID) -> None:
        if supplier.company_id != self._company_id or any(
            site.company_id != self._company_id or site.supplier_id != supplier.id
            for site in supplier.sites
        ):
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The supplier is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    @staticmethod
    def _validate_filters(
        *, status: SupplierStatus | None, kind: SupplierKind | None, limit: int, offset: int
    ) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        if status is not None and not isinstance(status, SupplierStatus):
            raise ValueError("status must be an official M6 status.")
        if kind is not None and not isinstance(kind, SupplierKind):
            raise ValueError("kind must be an official M6 supplier kind.")

    async def _flush_conflict(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise SupplierConflictError from error
            raise


__all__ = ["SupplierConflictError", "SupplierRepository", "_site", "_supplier"]
