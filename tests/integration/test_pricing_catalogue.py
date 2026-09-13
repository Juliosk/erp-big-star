"""M9 pricing catalogue services and repositories use real PostgreSQL."""

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import delete

from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.pricing.application import (
    CreatePriceList,
    CreatePriceListVersion,
    PricingAuthorization,
    PricingCatalogService,
)
from erp.modules.pricing.application.permissions import (
    PRICING_PRICE_CREATE,
    PRICING_SIMULATE,
)
from erp.modules.pricing.domain import PriceListStatus, PriceListVersionStatus, PriceType
from erp.modules.pricing.infrastructure import (
    MinimumMarginPolicyModel,
    PostgresPricingCatalogue,
    PriceListItemModel,
    PriceListModel,
    PriceListVersionModel,
    PricingSnapshotModel,
)
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


def _security_context(
    data: Fixture, *, create: bool = True, include_other_company: bool = False
) -> SecurityContext:
    permissions = {PRICING_SIMULATE}
    if create:
        permissions.add(PRICING_PRICE_CREATE)
    scopes = {Scope(ScopeType.COMPANY, data.company_id)}
    if include_other_company:
        scopes.add(Scope(ScopeType.COMPANY, data.other_company_id))
    return SecurityContext(
        principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(permissions),
        scopes=frozenset(scopes),
    )


async def _cleanup_pricing(data: Fixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(
            delete(PricingSnapshotModel).where(PricingSnapshotModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(MinimumMarginPolicyModel).where(
                MinimumMarginPolicyModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(PriceListItemModel).where(PriceListItemModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(PriceListVersionModel).where(
                PriceListVersionModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(PriceListModel).where(PriceListModel.company_id.in_(company_ids))
        )


def test_pricing_catalogue_creates_lists_and_draft_versions_company_scoped() -> None:
    async def scenario() -> None:
        async with fixture() as data:
            try:
                service = PricingCatalogService(
                    PostgresPricingCatalogue(data.database, ttl_seconds=86400),
                    PricingAuthorization(
                        CompanyAccessService(PostgresCorporateDirectory(data.database))
                    ),
                )
                context = _security_context(data, include_other_company=True)
                price_list = await service.create_price_list(
                    context,
                    CreatePriceList(
                        company_id=data.company_id,
                        code="varejo",
                        name="Tabela Varejo",
                        price_type=PriceType.BASE,
                    ),
                )
                first = await service.create_price_list_version(
                    context,
                    CreatePriceListVersion(
                        company_id=data.company_id,
                        price_list_id=price_list.id,
                        valid_from=date(2026, 9, 13),
                        source="legacy_opening",
                    ),
                )
                second = await service.create_price_list_version(
                    context,
                    CreatePriceListVersion(
                        company_id=data.company_id,
                        price_list_id=price_list.id,
                        valid_from=date(2026, 10, 1),
                    ),
                )
                lists = await service.list_price_lists(
                    context,
                    data.company_id,
                    page=1,
                    page_size=20,
                    status=PriceListStatus.ACTIVE,
                )
                versions = await service.list_price_list_versions(
                    context,
                    data.company_id,
                    price_list.id,
                    page=1,
                    page_size=20,
                )

                assert lists.items == (price_list,)
                assert first.version_number == 1
                assert first.status is PriceListVersionStatus.DRAFT
                assert first.source == "LEGACY_OPENING"
                assert second.version_number == 2
                assert [version.version_number for version in versions.items] == [2, 1]
                assert (
                    await service.list_price_lists(
                        context,
                        data.other_company_id,
                        page=1,
                        page_size=20,
                    )
                ).items == ()
            finally:
                await _cleanup_pricing(data)

    asyncio.run(scenario())


def test_pricing_catalogue_rejects_duplicate_code_and_missing_permission() -> None:
    async def scenario() -> None:
        async with fixture() as data:
            try:
                service = PricingCatalogService(
                    PostgresPricingCatalogue(data.database, ttl_seconds=86400),
                    PricingAuthorization(
                        CompanyAccessService(PostgresCorporateDirectory(data.database))
                    ),
                )
                await service.create_price_list(
                    _security_context(data),
                    CreatePriceList(
                        company_id=data.company_id,
                        code="ATACADO",
                        name="Tabela Atacado",
                    ),
                )
                with pytest.raises(ApplicationError) as duplicate:
                    await service.create_price_list(
                        _security_context(data),
                        CreatePriceList(
                            company_id=data.company_id,
                            code="atacado",
                            name="Outra Tabela",
                        ),
                    )
                with pytest.raises(ApplicationError) as forbidden:
                    await service.create_price_list(
                        _security_context(data, create=False),
                        CreatePriceList(
                            company_id=data.company_id,
                            code="SEM-PERMISSAO",
                            name="Sem permissão",
                        ),
                    )

                assert duplicate.value.code == "PRICING_PRICE_LIST_CONFLICT"
                assert forbidden.value.code == "PERMISSION_FORBIDDEN"
            finally:
                await _cleanup_pricing(data)

    asyncio.run(scenario())
