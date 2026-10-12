"""M12 payable repositories integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect
from sqlalchemy.exc import IntegrityError

from erp.modules.finance.domain import (
    FinanceScopeError,
    FinanceVersionConflictError,
    Payable,
    PayableConflictError,
    PayableSegregationPolicy,
    PayableStatus,
    ProvisionalEntryOrigin,
    ProvisionalFinancialEntry,
)
from erp.modules.finance.infrastructure import (
    PayableInstallmentModel,
    PayableModel,
    PayableRepository,
    ProvisionalEntryModel,
    ProvisionalEntryRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_procurement_supplier_repository import (
    ProcurementFixture,
    procurement_fixture,
)

pytestmark = pytest.mark.integration


@asynccontextmanager
async def finance_fixture() -> AsyncIterator[ProcurementFixture]:
    async with procurement_fixture() as data:
        companies = (data.company_id, data.other_company_id)
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(PayableInstallmentModel).where(
                        PayableInstallmentModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(PayableModel).where(PayableModel.company_id.in_(companies))
                )
                await session.execute(
                    delete(ProvisionalEntryModel).where(
                        ProvisionalEntryModel.company_id.in_(companies)
                    )
                )


def _provision(
    data: ProcurementFixture,
    *,
    company_id: UUID | None = None,
    source_id: UUID | None = None,
) -> ProvisionalFinancialEntry:
    return ProvisionalFinancialEntry.create(
        company_id=company_id or data.company_id,
        origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
        source_id=source_id or uuid4(),
        source_version=1,
        supplier_id=uuid4(),
        supplier_tax_id="12.345.678/0001-95",
        amount=Decimal("110.00"),
        created_by=data.actor_id,
    )


def _payable(
    data: ProcurementFixture,
    *,
    company_id: UUID | None = None,
    number: str = "AP-158",
    supplier_id: UUID | None = None,
    provisional_entry_id: UUID | None = None,
) -> Payable:
    return Payable.create(
        company_id=company_id or data.company_id,
        number=number,
        supplier_id=supplier_id or uuid4(),
        supplier_tax_id="12.345.678/0001-95",
        created_by=data.actor_id,
        provisional_entry_id=provisional_entry_id,
        nominal_amount=Decimal("100.00"),
        interest_amount=Decimal("10.00"),
        installment_plan=(
            (date(2026, 11, 10), Decimal("50.00")),
            (date(2026, 12, 10), Decimal("60.00")),
        ),
    )


def test_payable_and_provisional_round_trip_preserves_installments_and_history() -> None:
    async def scenario() -> None:
        async with finance_fixture() as data:
            provision = _provision(data)
            title = _payable(data, provisional_entry_id=provision.id)
            async with data.database.session() as session, session.begin():
                provisions = ProvisionalEntryRepository(session, company_id=data.company_id)
                payables = PayableRepository(session, company_id=data.company_id)
                await provisions.add(provision, actor_id=data.actor_id)
                await payables.add(title, actor_id=data.actor_id)
                converted = provision.convert(title.id)
                await provisions.save(converted, actor_id=data.actor_id)
                assert await provisions.get(provision.id) == converted
                assert (
                    await provisions.get_by_source(
                        origin=provision.origin,
                        source_id=provision.source_id,
                        source_version=provision.source_version,
                    )
                    == converted
                )
                assert await payables.get(title.id) == title
                assert await payables.list(status=PayableStatus.DRAFT) == (title,)

                pending = title.submit_for_approval()
                await payables.save(pending, actor_id=data.actor_id)
                approved = pending.approve(
                    approver_id=uuid4(),
                    policy=PayableSegregationPolicy(Decimal("100.00")),
                )
                await payables.save(approved, actor_id=data.actor_id)
                scheduled = approved.schedule((uuid4(), uuid4()))
                await payables.save(scheduled, actor_id=data.actor_id)
                partially_paid = scheduled.mark_installment_paid(
                    installment_number=1,
                    paid_on=date(2026, 11, 10),
                    payment_reference="BANK-158-1",
                )
                await payables.save(partially_paid, actor_id=data.actor_id)
                paid = partially_paid.mark_installment_paid(
                    installment_number=2,
                    paid_on=date(2026, 12, 10),
                    payment_reference="BANK-158-2",
                )
                await payables.save(paid, actor_id=data.actor_id)
                assert await payables.get(title.id) == paid
                assert await payables.list(supplier_id=title.supplier_id) == (paid,)

    asyncio.run(scenario())


def test_repositories_are_tenant_bound_and_source_identity_is_company_scoped() -> None:
    async def scenario() -> None:
        async with (
            finance_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            shared_source = uuid4()
            own_provision = _provision(data, source_id=shared_source)
            foreign_provision = _provision(
                data,
                company_id=data.other_company_id,
                source_id=shared_source,
            )
            own_title = _payable(data)
            foreign_title = _payable(data, company_id=data.other_company_id)
            own_provisions = ProvisionalEntryRepository(session, company_id=data.company_id)
            foreign_provisions = ProvisionalEntryRepository(
                session, company_id=data.other_company_id
            )
            own_payables = PayableRepository(session, company_id=data.company_id)
            foreign_payables = PayableRepository(session, company_id=data.other_company_id)
            await own_provisions.add(own_provision, actor_id=data.actor_id)
            await foreign_provisions.add(foreign_provision, actor_id=data.actor_id)
            await own_payables.add(own_title, actor_id=data.actor_id)
            await foreign_payables.add(foreign_title, actor_id=data.actor_id)

            assert await own_provisions.get(foreign_provision.id) is None
            assert await own_payables.get(foreign_title.id) is None
            with pytest.raises(FinanceScopeError):
                await foreign_provisions.add(own_provision, actor_id=data.actor_id)
            with pytest.raises(FinanceScopeError):
                await foreign_payables.add(own_title, actor_id=data.actor_id)

    asyncio.run(scenario())


def test_duplicate_payable_and_provisional_source_are_domain_conflicts() -> None:
    async def scenario() -> None:
        async with (
            finance_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            supplier_id = uuid4()
            title = _payable(data, supplier_id=supplier_id)
            duplicate_title = _payable(data, supplier_id=supplier_id)
            provision = _provision(data)
            duplicate_provision = replace(provision, id=uuid4())
            payables = PayableRepository(session, company_id=data.company_id)
            provisions = ProvisionalEntryRepository(session, company_id=data.company_id)
            await payables.add(title, actor_id=data.actor_id)
            await provisions.add(provision, actor_id=data.actor_id)

            savepoint = await session.begin_nested()
            with pytest.raises(PayableConflictError):
                await payables.add(duplicate_title, actor_id=data.actor_id)
            await savepoint.rollback()
            savepoint = await session.begin_nested()
            with pytest.raises(PayableConflictError):
                await provisions.add(duplicate_provision, actor_id=data.actor_id)
            await savepoint.rollback()

    asyncio.run(scenario())


def test_stale_payable_and_provisional_updates_raise_version_conflict() -> None:
    async def scenario() -> None:
        async with (
            finance_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            provision = _provision(data)
            title = _payable(data)
            provisions = ProvisionalEntryRepository(session, company_id=data.company_id)
            payables = PayableRepository(session, company_id=data.company_id)
            await provisions.add(provision, actor_id=data.actor_id)
            await payables.add(title, actor_id=data.actor_id)
            pending = title.submit_for_approval()
            await payables.save(pending, actor_id=data.actor_id)
            with pytest.raises(FinanceVersionConflictError):
                await payables.save(pending, actor_id=data.actor_id, expected_version=1)
            voided = provision.void("Documento fiscal cancelado")
            await provisions.save(voided, actor_id=data.actor_id)
            with pytest.raises(FinanceVersionConflictError):
                await provisions.save(voided, actor_id=data.actor_id, expected_version=1)

    asyncio.run(scenario())


def test_provisional_lookup_rejects_ambiguous_source_and_purchase_matches() -> None:
    async def scenario() -> None:
        async with (
            finance_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            source_id = uuid4()
            first = replace(
                _provision(data, source_id=source_id),
                origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
            )
            second = replace(first, id=uuid4(), source_version=2)
            repository = ProvisionalEntryRepository(session, company_id=data.company_id)
            await repository.add(first, actor_id=data.actor_id)
            await repository.add(second, actor_id=data.actor_id)

            with pytest.raises(PayableConflictError, match="same source"):
                await repository.get_by_source_id(
                    origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
                    source_id=source_id,
                )
            with pytest.raises(PayableConflictError, match="supplier and amount"):
                await repository.find_purchase_order_match(
                    supplier_tax_id=first.supplier_tax_id,
                    amount=first.amount,
                )

    asyncio.run(scenario())


def test_repository_contract_requires_explicit_scope_actor_version_and_filters() -> None:
    async def scenario() -> None:
        async with (
            finance_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            title = _payable(data)
            provision = _provision(data)
            with pytest.raises(ValueError, match="company UUID"):
                PayableRepository(session, company_id="invalid")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="company UUID"):
                ProvisionalEntryRepository(session, company_id="invalid")  # type: ignore[arg-type]
            payables = PayableRepository(session, company_id=data.company_id)
            provisions = ProvisionalEntryRepository(session, company_id=data.company_id)
            with pytest.raises(ValueError, match="actor UUID"):
                await payables.add(title, actor_id="invalid")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="actor UUID"):
                await provisions.add(provision, actor_id="invalid")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="start draft"):
                await payables.add(title.submit_for_approval(), actor_id=data.actor_id)
            with pytest.raises(ValueError, match="start open"):
                await provisions.add(provision.void("cancelled"), actor_id=data.actor_id)
            await payables.add(title, actor_id=data.actor_id)
            await provisions.add(provision, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="version increment"):
                await payables.save(title, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="version increment"):
                await provisions.save(provision, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="limit"):
                await payables.list(limit=0)
            with pytest.raises(ValueError, match="offset"):
                await payables.list(offset=-1)
            with pytest.raises(ValueError, match="official payable"):
                await payables.list(status="DRAFT")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="supplier_id"):
                await payables.list(supplier_id="invalid")  # type: ignore[arg-type]

            unexpected = IntegrityError("statement", {}, RuntimeError("database error"))
            with pytest.raises(IntegrityError) as captured:
                payables._translate(unexpected)
            assert captured.value is unexpected
            with pytest.raises(IntegrityError) as captured:
                provisions._translate(unexpected)
            assert captured.value is unexpected

    asyncio.run(scenario())


def test_migration_0039_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    schemas = set(inspect(sync_connection).get_schema_names())
                    assert ("finance" in schemas) is expected
                    if not expected:
                        return
                    inspector = inspect(sync_connection)
                    assert set(inspector.get_table_names(schema="finance")) == {
                        "payable",
                        "payable_installment",
                        "provisional_entry",
                    }
                    payable_uniques = {
                        value["name"]
                        for value in inspector.get_unique_constraints("payable", schema="finance")
                    }
                    assert "uq_payable_company_document_supplier" in payable_uniques
                    installment_fks = inspector.get_foreign_keys(
                        "payable_installment", schema="finance"
                    )
                    assert any(
                        value["constrained_columns"] == ["company_id", "payable_id"]
                        for value in installment_fks
                    )
                    payable_fks = inspector.get_foreign_keys("payable", schema="finance")
                    assert any(
                        value["constrained_columns"] == ["company_id", "provisional_entry_id"]
                        for value in payable_fks
                    )

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0038")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0039")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")
