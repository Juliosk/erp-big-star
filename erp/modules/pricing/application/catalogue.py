"""Authorized catalogue services for M9 Pricing."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.pricing.application.commands import (
    ActivatePriceListVersion,
    CreatePriceList,
    CreatePriceListVersion,
    PricingCatalogue,
    PricingCommandResult,
    PricingPage,
)
from erp.modules.pricing.application.permissions import (
    PRICING_PRICE_ACTIVATE,
    PRICING_PRICE_CREATE,
    PRICING_SIMULATE,
    PricingAuthorization,
)
from erp.modules.pricing.domain import (
    Money,
    Percentage,
    PriceList,
    PriceListItem,
    PriceListStatus,
    PriceListVersion,
)
from erp.platform.errors import ApplicationError, ErrorDetail

T = TypeVar("T")


class PricingCatalogService:
    """Build validated pricing aggregates after RBAC and company checks."""

    def __init__(self, store: PricingCatalogue, authorization: PricingAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create_price_list(
        self, context: SecurityContext, command: CreatePriceList
    ) -> PriceList:
        await self._authorization.require(
            context, command.company_id, PRICING_PRICE_CREATE, write=True
        )
        price_list = self._build(
            lambda: PriceList.create(
                company_id=command.company_id,
                code=command.code,
                name=command.name,
                price_type=command.price_type,
                currency=command.currency,
            )
        )
        return await self._store.create_price_list(price_list, context.principal.user_id)

    async def create_price_list_version(
        self, context: SecurityContext, command: CreatePriceListVersion
    ) -> PriceListVersion:
        await self._authorization.require(
            context, command.company_id, PRICING_PRICE_CREATE, write=True
        )
        if await self._store.get_price_list(command.company_id, command.price_list_id) is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Price list not found in the selected company.",
                status_code=404,
            )
        version_number = await self._store.next_version_number(
            command.company_id, command.price_list_id
        )
        price_list_version = self._build(
            lambda: PriceListVersion.draft(
                company_id=command.company_id,
                price_list_id=command.price_list_id,
                version_number=version_number,
                valid_from=command.valid_from,
                valid_to=command.valid_to,
                source=command.source,
                items=tuple(
                    PriceListItem.create(
                        company_id=command.company_id,
                        version_id=command.price_list_id,
                        product_id=item.product_id,
                        price=Money.brl(item.price_amount),
                        minimum_price=(
                            None
                            if item.minimum_price_amount is None
                            else Money.brl(item.minimum_price_amount)
                        ),
                        target_margin=(
                            None
                            if item.target_margin is None
                            else Percentage.ratio(item.target_margin)
                        ),
                    )
                    for item in command.items
                ),
            )
        )
        return await self._store.create_price_list_version(
            price_list_version, context.principal.user_id
        )

    async def activate_price_list_version(
        self, context: SecurityContext, command: ActivatePriceListVersion
    ) -> PricingCommandResult:
        await self._authorization.require(
            context, command.company_id, PRICING_PRICE_ACTIVATE, write=True
        )
        return await self._store.activate_price_list_version(
            command, context.principal.user_id
        )

    async def list_price_lists(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PriceListStatus | None = None,
    ) -> PricingPage[PriceList]:
        await self._authorization.require(context, company_id, PRICING_SIMULATE)
        return await self._store.list_price_lists(
            company_id, page=page, page_size=page_size, status=status
        )

    async def get_price_list(
        self, context: SecurityContext, company_id: UUID, price_list_id: UUID
    ) -> PriceList:
        await self._authorization.require(context, company_id, PRICING_SIMULATE)
        result = await self._store.get_price_list(company_id, price_list_id)
        if result is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Price list not found in the selected company.",
                status_code=404,
            )
        return result

    async def list_price_list_versions(
        self,
        context: SecurityContext,
        company_id: UUID,
        price_list_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> PricingPage[PriceListVersion]:
        await self._authorization.require(context, company_id, PRICING_SIMULATE)
        if await self._store.get_price_list(company_id, price_list_id) is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Price list not found in the selected company.",
                status_code=404,
            )
        return await self._store.list_price_list_versions(
            company_id,
            price_list_id,
            page=page,
            page_size=page_size,
        )

    async def get_price_list_version(
        self, context: SecurityContext, company_id: UUID, price_list_version_id: UUID
    ) -> PriceListVersion:
        await self._authorization.require(context, company_id, PRICING_SIMULATE)
        result = await self._store.get_price_list_version(company_id, price_list_version_id)
        if result is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Price-list version not found in the selected company.",
                status_code=404,
            )
        return result

    @staticmethod
    def _build(factory: Callable[[], T]) -> T:
        try:
            return factory()
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid pricing data.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error


__all__ = ["PricingCatalogService"]
