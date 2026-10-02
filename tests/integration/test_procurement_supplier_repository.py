"""M6 supplier repository tests against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from erp.modules.admin.domain import Company, EconomicGroup
from erp.modules.admin.infrastructure import (
    CompanyModel,
    CompanyRepository,
    EconomicGroupModel,
    EconomicGroupRepository,
)
from erp.modules.procurement.domain import (
    Supplier,
    SupplierAddress,
    SupplierIdentityKind,
    SupplierKind,
    SupplierSite,
    SupplierStatus,
)
from erp.modules.procurement.infrastructure import (
    SupplierConflictError,
    SupplierModel,
    SupplierRepository,
    SupplierSiteModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError

pytestmark = pytest.mark.integration


def _cnpj() -> str:
    value = f"12{uuid4().int % 10_000_000_000:010d}"
    for weights in (
        (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
        (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
    ):
        remainder = (
            sum(int(digit) * weight for digit, weight in zip(value, weights, strict=True)) % 11
        )
        value += str(0 if remainder < 2 else 11 - remainder)
    return value


@dataclass(frozen=True)
class ProcurementFixture:
    database: Database
    company_id: UUID
    other_company_id: UUID
    actor_id: UUID

    def supplier(
        self,
        *,
        company_id: UUID | None = None,
        legal_name: str = "Fornecedor fixture",
        identity_value: str | None = None,
    ) -> Supplier:
        return Supplier.create(
            company_id=company_id or self.company_id,
            kind=SupplierKind.COMPANY,
            identity_kind=SupplierIdentityKind.CNPJ,
            identity_value=identity_value or _cnpj(),
            identity_country_code="BR",
            legal_name=legal_name,
        )

    def site(self, supplier: Supplier, *, code: str = "MATRIZ") -> SupplierSite:
        return SupplierSite.create(
            company_id=supplier.company_id,
            supplier_id=supplier.id,
            code=code,
            name=f"Site {code}",
            address=SupplierAddress.create(
                line1="Rua do fornecedor, 10",
                city="Sao Paulo",
                country_code="BR",
                state="SP",
                postal_code="01001000",
            ),
            email="compras@fornecedor.example",
            phone="+55 11 3333-4444",
            is_primary=code == "MATRIZ",
        )


@asynccontextmanager
async def procurement_fixture() -> AsyncIterator[ProcurementFixture]:
    database = Database(get_settings())
    actor_id = uuid4()
    group = EconomicGroup.create(code=f"P{uuid4().hex[:20]}", name="M6 test fixture")
    companies = tuple(
        Company.create(
            group_id=group.id,
            code=f"P{uuid4().hex[:20]}",
            legal_name="M6 test company",
            trade_name=None,
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        for _ in range(2)
    )
    company_ids = tuple(company.id for company in companies)
    try:
        async with database.session() as session, session.begin():
            await EconomicGroupRepository().add(session, group, actor_id=actor_id)
            for company in companies:
                await CompanyRepository().add(session, company, actor_id=actor_id)
        yield ProcurementFixture(database, companies[0].id, companies[1].id, actor_id)
    finally:
        try:
            async with database.session() as session, session.begin():
                await session.execute(
                    delete(SupplierSiteModel).where(SupplierSiteModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(SupplierModel).where(SupplierModel.company_id.in_(company_ids))
                )
                await session.execute(delete(CompanyModel).where(CompanyModel.id.in_(company_ids)))
                await session.execute(
                    delete(EconomicGroupModel).where(EconomicGroupModel.id == group.id)
                )
        finally:
            await database.dispose()


def test_supplier_round_trip_with_complete_site_mapping() -> None:
    async def scenario() -> None:
        async with procurement_fixture() as data:
            supplier = data.supplier()
            async with data.database.session() as session, session.begin():
                repository = SupplierRepository(session, company_id=data.company_id)
                await repository.add(supplier, actor_id=data.actor_id)
                with_site = supplier.add_site(data.site(supplier))
                assert await repository.save(with_site, actor_id=data.actor_id) == with_site
                assert await repository.get(supplier.id) == with_site
            async with data.database.session() as session:
                model = await session.get(SupplierModel, supplier.id)
                assert model is not None
                assert model.identity_value == supplier.tax_identity.value
                assert model.version == 2
                site_model = await session.get(SupplierSiteModel, with_site.sites[0].id)
                assert site_model is not None
                assert site_model.company_id == data.company_id
                assert site_model.created_by == data.actor_id

    asyncio.run(scenario())


def test_get_and_list_never_cross_company_boundary() -> None:
    async def scenario() -> None:
        async with (
            procurement_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            shared_identity = _cnpj()
            own = data.supplier(legal_name="A Supplier", identity_value=shared_identity)
            foreign = data.supplier(
                company_id=data.other_company_id,
                legal_name="B Supplier",
                identity_value=shared_identity,
            )
            own_repo = SupplierRepository(session, company_id=data.company_id)
            foreign_repo = SupplierRepository(session, company_id=data.other_company_id)
            await own_repo.add(own, actor_id=data.actor_id)
            await foreign_repo.add(foreign, actor_id=data.actor_id)
            assert await own_repo.list() == (own,)
            assert await own_repo.list(kind=SupplierKind.COMPANY) == (own,)
            assert await foreign_repo.list() == (foreign,)
            assert await own_repo.get(foreign.id) is None
            assert await SupplierRepository(session, company_id=uuid4()).list() == ()

    asyncio.run(scenario())


def test_scope_mismatch_is_rejected_before_write() -> None:
    async def scenario() -> None:
        async with (
            procurement_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            foreign = data.supplier(company_id=data.other_company_id)
            repository = SupplierRepository(session, company_id=data.company_id)
            with pytest.raises(ApplicationError) as captured:
                await repository.add(foreign, actor_id=data.actor_id)
            assert captured.value.code == "SCOPE_FORBIDDEN"
            assert await session.get(SupplierModel, foreign.id) is None

    asyncio.run(scenario())


def test_fiscal_identity_and_site_code_conflicts_are_tenant_local() -> None:
    async def scenario() -> None:
        async with (
            procurement_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            identity = _cnpj()
            first = data.supplier(identity_value=identity)
            repository = SupplierRepository(session, company_id=data.company_id)
            await repository.add(first, actor_id=data.actor_id)
            async with session.begin_nested() as savepoint:
                with pytest.raises(SupplierConflictError) as captured:
                    await repository.add(
                        data.supplier(legal_name="Duplicado", identity_value=identity),
                        actor_id=data.actor_id,
                    )
                assert captured.value.code == "SUPPLIER_CONFLICT"
                await savepoint.rollback()

            second = data.supplier(legal_name="Segundo")
            await repository.add(second, actor_id=data.actor_id)
            first_with_site = first.add_site(data.site(first, code="CD01"))
            await repository.save(first_with_site, actor_id=data.actor_id)
            async with session.begin_nested() as savepoint:
                with pytest.raises(SupplierConflictError) as captured:
                    await repository.save(
                        second.add_site(data.site(second, code="CD01")),
                        actor_id=data.actor_id,
                    )
                assert captured.value.status_code == 409
                await savepoint.rollback()

    asyncio.run(scenario())


def test_lifecycle_transitions_are_persisted_with_optimistic_version() -> None:
    async def scenario() -> None:
        async with (
            procurement_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            supplier = data.supplier()
            repository = SupplierRepository(session, company_id=data.company_id)
            await repository.add(supplier, actor_id=data.actor_id)
            inactive = supplier.transition_status(SupplierStatus.INACTIVE)
            assert await repository.save(inactive, actor_id=data.actor_id) == inactive
            active = inactive.transition_status(SupplierStatus.ACTIVE)
            assert await repository.save(active, actor_id=data.actor_id) == active
            blocked = active.transition_status(SupplierStatus.BLOCKED)
            assert await repository.save(blocked, actor_id=data.actor_id) == blocked
            assert await repository.list(status=SupplierStatus.BLOCKED) == (blocked,)

    asyncio.run(scenario())


def test_concurrent_saves_have_one_winner_and_one_version_conflict() -> None:
    async def scenario() -> None:
        async with procurement_fixture() as data:
            supplier = data.supplier()
            async with data.database.session() as session, session.begin():
                await SupplierRepository(session, company_id=data.company_id).add(
                    supplier, actor_id=data.actor_id
                )
            barrier = asyncio.Barrier(2)

            async def change(name: str) -> Supplier | OptimisticLockError:
                try:
                    async with data.database.session() as session, session.begin():
                        repository = SupplierRepository(session, company_id=data.company_id)
                        snapshot = await repository.get(supplier.id)
                        assert snapshot is not None
                        await asyncio.wait_for(barrier.wait(), timeout=10)
                        return await repository.save(
                            snapshot.update_master(legal_name=name, trade_name=None),
                            actor_id=data.actor_id,
                        )
                except OptimisticLockError as error:
                    return error

            results = await asyncio.wait_for(
                asyncio.gather(change("Winner A"), change("Winner B")), timeout=20
            )
            assert sum(isinstance(item, Supplier) for item in results) == 1
            conflicts = [item for item in results if isinstance(item, OptimisticLockError)]
            assert len(conflicts) == 1
            assert conflicts[0].code == "VERSION_CONFLICT"

    asyncio.run(scenario())


def test_identity_is_immutable_and_foreign_id_cannot_be_saved() -> None:
    async def scenario() -> None:
        async with (
            procurement_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            supplier = data.supplier()
            own_repo = SupplierRepository(session, company_id=data.company_id)
            await own_repo.add(supplier, actor_id=data.actor_id)
            changed = supplier.update_master(legal_name="Changed", trade_name=None)
            object.__setattr__(changed.tax_identity, "value", _cnpj())
            with pytest.raises(OptimisticLockError):
                await own_repo.save(changed, actor_id=data.actor_id)

            foreign_candidate = replace(
                supplier.update_master(legal_name="Forbidden", trade_name=None),
                company_id=data.other_company_id,
            )
            with pytest.raises(ApplicationError) as captured:
                await own_repo.save(foreign_candidate, actor_id=data.actor_id)
            assert captured.value.code == "SCOPE_FORBIDDEN"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (101, 0), (True, 0), (1, -1), (1, True)],
)
def test_repository_rejects_invalid_pagination(limit: int, offset: int) -> None:
    async def scenario() -> None:
        async with procurement_fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match=r"limit|offset"):
                await SupplierRepository(session, company_id=data.company_id).list(
                    limit=limit, offset=offset
                )

    asyncio.run(scenario())


def test_repository_rejects_invalid_context_actor_state_and_filters() -> None:
    async def scenario() -> None:
        async with procurement_fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match="company"):
                SupplierRepository(session, company_id=None)  # type: ignore[arg-type]
            repository = SupplierRepository(session, company_id=data.company_id)
            with pytest.raises(ValueError, match="actor"):
                await repository.add(data.supplier(), actor_id=None)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="version one"):
                await repository.add(replace(data.supplier(), version=2), actor_id=data.actor_id)
            with pytest.raises(ValueError, match="active"):
                await repository.add(
                    replace(data.supplier(), status=SupplierStatus.BLOCKED),
                    actor_id=data.actor_id,
                )
            supplier = data.supplier()
            with pytest.raises(ValueError, match="cannot already contain sites"):
                await repository.add(
                    replace(supplier, sites=(data.site(supplier),)), actor_id=data.actor_id
                )
            with pytest.raises(ValueError, match="status"):
                await repository.list(status="BAD")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="kind"):
                await repository.list(kind="BAD")  # type: ignore[arg-type]
            supplier = data.supplier()
            await repository.add(supplier, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="newer than expected"):
                await repository.save(
                    supplier, actor_id=data.actor_id, expected_version=supplier.version
                )

    asyncio.run(scenario())
