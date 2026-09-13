"""PostgreSQL adapter for M9 pricing catalogue reads and writes."""

from uuid import UUID

from erp.modules.pricing.application.commands import (
    ActivatePriceListVersion,
    PricingCatalogue,
    PricingCommandResult,
    PricingPage,
)
from erp.modules.pricing.domain import PriceList, PriceListStatus, PriceListVersion
from erp.modules.pricing.infrastructure.price_list_repository import PriceListRepository
from erp.platform.database import Database


class PostgresPricingCatalogue(PricingCatalogue):
    """Session-owning adapter; lower repositories remain company-scoped."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_price_list(self, price_list: PriceList, actor_id: UUID) -> PriceList:
        async with self._database.session() as session, session.begin():
            await PriceListRepository(session, company_id=price_list.company_id).add_price_list(
                price_list, actor_id=actor_id
            )
        return price_list

    async def create_price_list_version(
        self, version: PriceListVersion, actor_id: UUID
    ) -> PriceListVersion:
        async with self._database.session() as session, session.begin():
            await PriceListRepository(
                session, company_id=version.company_id
            ).add_price_list_version(version, actor_id=actor_id)
        return version

    async def activate_price_list_version(
        self, command: ActivatePriceListVersion, actor_id: UUID
    ) -> PricingCommandResult:
        raise NotImplementedError("Activation is delivered by Sprint 8 Commit 084.")

    async def get_price_list(self, company_id: UUID, price_list_id: UUID) -> PriceList | None:
        async with self._database.session() as session:
            return await PriceListRepository(session, company_id=company_id).get_price_list(
                price_list_id
            )

    async def list_price_lists(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PriceListStatus | None,
    ) -> PricingPage[PriceList]:
        async with self._database.session() as session:
            repository = PriceListRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list_price_lists(
                limit=page_size, offset=offset, status=status
            )
            more = await repository.list_price_lists(
                limit=1, offset=offset + page_size, status=status
            )
            return PricingPage(items, page, page_size, bool(more))

    async def next_version_number(self, company_id: UUID, price_list_id: UUID) -> int:
        async with self._database.session() as session:
            return await PriceListRepository(
                session, company_id=company_id
            ).next_version_number(price_list_id)

    async def list_price_list_versions(
        self,
        company_id: UUID,
        price_list_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> PricingPage[PriceListVersion]:
        async with self._database.session() as session:
            repository = PriceListRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list_price_list_versions(
                price_list_id, limit=page_size, offset=offset
            )
            more = await repository.list_price_list_versions(
                price_list_id, limit=1, offset=offset + page_size
            )
            return PricingPage(items, page, page_size, bool(more))

    async def get_price_list_version(
        self, company_id: UUID, price_list_version_id: UUID
    ) -> PriceListVersion | None:
        async with self._database.session() as session:
            return await PriceListRepository(
                session, company_id=company_id
            ).get_price_list_version(price_list_version_id)


__all__ = ["PostgresPricingCatalogue"]
