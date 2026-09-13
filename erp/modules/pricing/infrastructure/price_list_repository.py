"""Tenant-bound persistence for M9 price lists and versions."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from erp.modules.pricing.domain import (
    Money,
    Percentage,
    PriceList,
    PriceListItem,
    PriceListStatus,
    PriceListVersion,
    PriceListVersionStatus,
    PriceType,
)
from erp.modules.pricing.infrastructure.price_list_model import (
    PriceListItemModel,
    PriceListModel,
    PriceListVersionModel,
)
from erp.platform.errors import ApplicationError


def _price_list(model: PriceListModel) -> PriceList:
    return PriceList(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        name=model.name,
        price_type=PriceType(model.price_type),
        currency=model.currency,
        status=PriceListStatus(model.status),
        version=model.version,
    )


def _price_item(model: PriceListItemModel) -> PriceListItem:
    return PriceListItem(
        id=model.id,
        company_id=model.company_id,
        version_id=model.price_list_version_id,
        product_id=model.product_id,
        price=Money.brl(model.price_amount),
        minimum_price=(
            None if model.minimum_price_amount is None else Money.brl(model.minimum_price_amount)
        ),
        target_margin=(
            None if model.target_margin is None else Percentage.ratio(model.target_margin)
        ),
    )


def _price_version(model: PriceListVersionModel) -> PriceListVersion:
    return PriceListVersion(
        id=model.id,
        company_id=model.company_id,
        price_list_id=model.price_list_id,
        version_number=model.version_number,
        status=PriceListVersionStatus(model.status),
        valid_from=model.valid_from,
        valid_to=model.valid_to,
        source=model.source,
        items=tuple(_price_item(item) for item in model.items),
        activated_at=model.activated_at,
        version=model.version,
    )


class PriceListRepository:
    """One previously authorized company per instance, with no unscoped operations."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add_price_list(self, price_list: PriceList, *, actor_id: UUID) -> None:
        self._validate_price_list_write(price_list, actor_id)
        self._session.add(
            PriceListModel(
                id=price_list.id,
                company_id=self._company_id,
                code=price_list.code,
                name=price_list.name,
                price_type=price_list.price_type,
                currency=price_list.currency,
                status=price_list.status,
                version=price_list.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_unique(code="PRICING_PRICE_LIST_CONFLICT")

    async def get_price_list(self, price_list_id: UUID) -> PriceList | None:
        result = await self._session.scalars(
            select(PriceListModel)
            .where(
                PriceListModel.company_id == self._company_id,
                PriceListModel.id == price_list_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _price_list(model)

    async def list_price_lists(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: PriceListStatus | None = None,
    ) -> tuple[PriceList, ...]:
        _validate_limit_offset(limit, offset)
        statement = select(PriceListModel).where(PriceListModel.company_id == self._company_id)
        if status is not None:
            statement = statement.where(PriceListModel.status == status)
        result = await self._session.scalars(
            statement.order_by(PriceListModel.code, PriceListModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_price_list(model) for model in result)

    async def next_version_number(self, price_list_id: UUID) -> int:
        current = await self._session.scalar(
            select(func.max(PriceListVersionModel.version_number)).where(
                PriceListVersionModel.company_id == self._company_id,
                PriceListVersionModel.price_list_id == price_list_id,
            )
        )
        return int(current or 0) + 1

    async def add_price_list_version(
        self, version: PriceListVersion, *, actor_id: UUID
    ) -> None:
        self._validate_price_version_write(version, actor_id)
        model = PriceListVersionModel(
            id=version.id,
            company_id=self._company_id,
            price_list_id=version.price_list_id,
            version_number=version.version_number,
            status=version.status,
            valid_from=version.valid_from,
            valid_to=version.valid_to,
            source=version.source,
            activated_at=version.activated_at,
            activated_by=None,
            version=version.version,
            created_by=actor_id,
            updated_by=actor_id,
        )
        model.items = [
            PriceListItemModel(
                id=item.id,
                company_id=self._company_id,
                price_list_version_id=version.id,
                product_id=item.product_id,
                price_amount=item.price.amount,
                minimum_price_amount=(
                    None if item.minimum_price is None else item.minimum_price.amount
                ),
                target_margin=None if item.target_margin is None else item.target_margin.value,
                currency=item.price.currency,
            )
            for item in version.items
        ]
        self._session.add(model)
        await self._flush_unique(code="PRICING_PRICE_LIST_VERSION_CONFLICT")

    async def list_price_list_versions(
        self,
        price_list_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PriceListVersion, ...]:
        _validate_limit_offset(limit, offset)
        result = await self._session.scalars(
            select(PriceListVersionModel)
            .options(selectinload(PriceListVersionModel.items))
            .where(
                PriceListVersionModel.company_id == self._company_id,
                PriceListVersionModel.price_list_id == price_list_id,
            )
            .order_by(PriceListVersionModel.version_number.desc(), PriceListVersionModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_price_version(model) for model in result)

    async def _flush_unique(self, *, code: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code=code,
                    message="A pricing identifier is already in use.",
                    status_code=409,
                ) from error
            raise

    def _validate_price_list_write(self, price_list: PriceList, actor_id: UUID) -> None:
        if price_list.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The price list is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    def _validate_price_version_write(
        self, version: PriceListVersion, actor_id: UUID
    ) -> None:
        if version.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The price-list version is outside the selected company.",
                status_code=403,
            )
        if version.activated_at is not None and version.activated_at.tzinfo is None:
            raise ValueError("Activation timestamp must be timezone-aware.")
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


def _validate_limit_offset(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["PriceListRepository"]
