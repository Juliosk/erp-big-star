"""PostgreSQL engineering selection used by planned-order conversion."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.application import ProductionEngineeringSelection
from erp.modules.production.infrastructure.bom_repository import BOMRepository
from erp.modules.production.infrastructure.routing_repository import RoutingRepository


class PostgresProductionEngineeringDirectory:
    """Resolve an exact, tenant-owned BOM/routing version effective for the plan."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def resolve(
        self,
        *,
        company_id: UUID,
        product_id: UUID,
        version_code: str,
        effective_on: date,
    ) -> ProductionEngineeringSelection | None:
        if company_id != self._company_id:
            return None
        bom = await BOMRepository(
            self._session,
            company_id=self._company_id,
        ).get(product_id, version_code)
        routing = await RoutingRepository(
            self._session,
            company_id=self._company_id,
        ).get(product_id, version_code)
        if bom is None or routing is None:
            return None
        if not (
            bom.version.effective_from <= effective_on
            and (
                bom.version.effective_until is None
                or effective_on <= bom.version.effective_until
            )
            and routing.version.effective_from <= effective_on
            and (
                routing.version.effective_until is None
                or effective_on <= routing.version.effective_until
            )
        ):
            return None
        return ProductionEngineeringSelection(bom=bom, routing=routing)


__all__ = ["PostgresProductionEngineeringDirectory"]
