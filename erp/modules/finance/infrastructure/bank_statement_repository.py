"""Tenant-bound persistence adapter for M12 bank statements."""

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    BankMovementStatus,
    BankStatement,
    BankStatementConflictError,
    BankStatementSource,
    BankTransactionKind,
    FinanceScopeError,
    FinanceVersionConflictError,
    InvalidBankStatementError,
)
from erp.modules.finance.infrastructure.bank_statement_model import (
    BankMovementModel,
    BankStatementModel,
    ConciliationRecordModel,
    StatementImportAuditModel,
)


class BankStatementRepository:
    """Persist statements without owning transaction boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(
        self,
        statement: BankStatement,
        *,
        actor_id: UUID,
        original_file_name: str | None,
        file_size_bytes: int,
    ) -> None:
        self._write_scope(statement, actor_id)
        _import_metadata(original_file_name, file_size_bytes)
        if statement.version != 1:
            raise ValueError("A new bank statement must start at version one.")
        self._session.add(_statement_model(statement, actor_id))
        await self._flush()
        self._session.add_all(_movement_models(statement, actor_id))
        self._session.add(
            _import_audit_model(
                statement,
                actor_id=actor_id,
                original_file_name=original_file_name,
                file_size_bytes=file_size_bytes,
            )
        )
        await self._flush()

    async def add_idempotent(
        self,
        statement: BankStatement,
        *,
        actor_id: UUID,
        original_file_name: str | None,
        file_size_bytes: int,
    ) -> tuple[BankStatement, bool]:
        """Insert once by tenant/account/hash without owning the transaction."""
        self._write_scope(statement, actor_id)
        _import_metadata(original_file_name, file_size_bytes)
        if statement.version != 1:
            raise ValueError("A new bank statement must start at version one.")
        inserted = await self._session.scalar(
            insert(BankStatementModel)
            .values(**_statement_values(statement, actor_id))
            .on_conflict_do_nothing(
                index_elements=("company_id", "bank_account_id", "source_hash")
            )
            .returning(BankStatementModel.id)
        )
        if inserted is None:
            existing = await self.get_by_hash(
                bank_account_id=statement.bank_account_id,
                source_hash=statement.source_hash,
            )
            if existing is None:
                raise BankStatementConflictError(
                    "Bank statement identity conflicts with another company-scoped import."
                )
            return existing, True
        self._session.add_all(_movement_models(statement, actor_id))
        self._session.add(
            _import_audit_model(
                statement,
                actor_id=actor_id,
                original_file_name=original_file_name,
                file_size_bytes=file_size_bytes,
            )
        )
        await self._flush()
        return statement, False

    async def get(self, statement_id: UUID) -> BankStatement | None:
        root = await self._session.scalar(
            select(BankStatementModel)
            .where(
                BankStatementModel.company_id == self._company_id,
                BankStatementModel.id == statement_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _statement(root, await self._movements(root.id))

    async def get_by_hash(
        self,
        *,
        bank_account_id: UUID,
        source_hash: str,
    ) -> BankStatement | None:
        _nonzero_uuid(bank_account_id, "bank_account_id")
        normalized_hash = _source_hash(source_hash)
        root = await self._session.scalar(
            select(BankStatementModel)
            .where(
                BankStatementModel.company_id == self._company_id,
                BankStatementModel.bank_account_id == bank_account_id,
                BankStatementModel.source_hash == normalized_hash,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _statement(root, await self._movements(root.id))

    async def list(
        self,
        *,
        bank_account_id: UUID | None = None,
        period_from: date | None = None,
        period_to: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[BankStatement, ...]:
        _page(limit, offset)
        if period_from is not None and period_to is not None and period_from > period_to:
            raise ValueError("period_from cannot be after period_to.")
        query = select(BankStatementModel).where(
            BankStatementModel.company_id == self._company_id
        )
        if bank_account_id is not None:
            _nonzero_uuid(bank_account_id, "bank_account_id")
            query = query.where(BankStatementModel.bank_account_id == bank_account_id)
        if period_from is not None:
            query = query.where(BankStatementModel.period_end >= period_from)
        if period_to is not None:
            query = query.where(BankStatementModel.period_start <= period_to)
        roots = await self._session.scalars(
            query.order_by(BankStatementModel.period_start, BankStatementModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        values = []
        for root in roots:
            values.append(_statement(root, await self._movements(root.id)))
        return tuple(values)

    async def save(
        self,
        statement: BankStatement,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> BankStatement:
        self._write_scope(statement, actor_id)
        compare = statement.version - 1 if expected_version is None else expected_version
        if compare < 1 or statement.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self.get(statement.id)
        if current is None or current.version != compare:
            raise FinanceVersionConflictError(
                f"Bank statement expected version {compare} is stale."
            )
        _validate_frozen_statement(current, statement)
        changes = _reconciliation_changes(current, statement)
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(BankStatementModel)
                .where(
                    BankStatementModel.company_id == self._company_id,
                    BankStatementModel.id == statement.id,
                    BankStatementModel.version == compare,
                )
                .values(
                    version=statement.version,
                    updated_at=datetime.now(UTC),
                    updated_by=actor_id,
                )
            ),
        )
        if updated.rowcount != 1:
            raise FinanceVersionConflictError(
                f"Bank statement expected version {compare} is stale."
            )
        for movement in changes:
            await self._session.execute(
                update(BankMovementModel)
                .where(
                    BankMovementModel.company_id == self._company_id,
                    BankMovementModel.bank_statement_id == statement.id,
                    BankMovementModel.id == movement.id,
                    BankMovementModel.status == BankMovementStatus.PENDING.value,
                )
                .values(
                    status=movement.status.value,
                    matched_reference_id=movement.matched_reference_id,
                    reconciled_at=movement.reconciled_at,
                    match_score=movement.match_score,
                    updated_at=datetime.now(UTC),
                    updated_by=actor_id,
                )
            )
            assert movement.matched_reference_id is not None
            assert movement.reconciled_at is not None
            assert movement.match_score is not None
            self._session.add(
                ConciliationRecordModel(
                    id=uuid4(),
                    company_id=statement.company_id,
                    bank_statement_id=statement.id,
                    bank_movement_id=movement.id,
                    matched_reference_id=movement.matched_reference_id,
                    match_score=movement.match_score,
                    reconciled_at=movement.reconciled_at,
                    actor_id=actor_id,
                    details={
                        "statement_version": statement.version,
                        "external_id": movement.external_id,
                        "document_number": movement.document_number,
                    },
                )
            )
        await self._flush()
        return statement

    async def import_audit(self, statement_id: UUID) -> StatementImportAuditModel | None:
        return cast(
            StatementImportAuditModel | None,
            await self._session.scalar(
                select(StatementImportAuditModel).where(
                    StatementImportAuditModel.company_id == self._company_id,
                    StatementImportAuditModel.bank_statement_id == statement_id,
                )
            )
        )

    async def conciliations(self, statement_id: UUID) -> tuple[ConciliationRecordModel, ...]:
        values = await self._session.scalars(
            select(ConciliationRecordModel)
            .where(
                ConciliationRecordModel.company_id == self._company_id,
                ConciliationRecordModel.bank_statement_id == statement_id,
            )
            .order_by(ConciliationRecordModel.reconciled_at, ConciliationRecordModel.id)
        )
        return tuple(values)

    async def _movements(self, statement_id: UUID) -> tuple[BankMovementModel, ...]:
        values = await self._session.scalars(
            select(BankMovementModel)
            .where(
                BankMovementModel.company_id == self._company_id,
                BankMovementModel.bank_statement_id == statement_id,
            )
            .order_by(BankMovementModel.sequence_number)
            .execution_options(populate_existing=True)
        )
        return tuple(values)

    def _write_scope(self, statement: BankStatement, actor_id: UUID) -> None:
        if not isinstance(statement, BankStatement):
            raise TypeError("statement must be a BankStatement.")
        if statement.company_id != self._company_id:
            raise FinanceScopeError("Bank statement is outside the selected company.")
        _nonzero_uuid(actor_id, "actor_id")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise BankStatementConflictError(
                    "Bank statement hash, movement or reconciliation already exists for this company."
                ) from error
            raise


def _statement_model(statement: BankStatement, actor_id: UUID) -> BankStatementModel:
    return BankStatementModel(**_statement_values(statement, actor_id))


def _statement_values(statement: BankStatement, actor_id: UUID) -> dict[str, object]:
    return {
        "id": statement.id,
        "company_id": statement.company_id,
        "bank_account_id": statement.bank_account_id,
        "bank_code": statement.bank_code,
        "account_reference": statement.account_reference,
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "imported_at": statement.imported_at,
        "source": statement.source.value,
        "source_hash": statement.source_hash,
        "opening_balance": statement.opening_balance,
        "closing_balance": statement.closing_balance,
        "version": statement.version,
        "created_by": actor_id,
        "updated_by": actor_id,
    }


def _import_audit_model(
    statement: BankStatement,
    *,
    actor_id: UUID,
    original_file_name: str | None,
    file_size_bytes: int,
) -> StatementImportAuditModel:
    return StatementImportAuditModel(
        id=uuid4(),
        company_id=statement.company_id,
        bank_statement_id=statement.id,
        source=statement.source.value,
        source_hash=statement.source_hash,
        original_file_name=original_file_name,
        file_size_bytes=file_size_bytes,
        movement_count=len(statement.movements),
        imported_at=statement.imported_at,
        actor_id=actor_id,
        details={
            "bank_account_id": str(statement.bank_account_id),
            "bank_code": statement.bank_code,
            "period_start": statement.period_start.isoformat(),
            "period_end": statement.period_end.isoformat(),
        },
    )


def _movement_models(
    statement: BankStatement,
    actor_id: UUID,
) -> list[BankMovementModel]:
    return [
        BankMovementModel(
            id=movement.id,
            company_id=movement.company_id,
            bank_statement_id=statement.id,
            sequence_number=sequence_number,
            bank_account_id=movement.bank_account_id,
            external_id=movement.external_id,
            booked_on=movement.booked_on,
            amount=movement.amount,
            direction=movement.direction.value,
            kind=movement.kind.value,
            description=movement.description,
            document_number=movement.document_number,
            status=movement.status.value,
            matched_reference_id=movement.matched_reference_id,
            reconciled_at=movement.reconciled_at,
            match_score=movement.match_score,
            created_by=actor_id,
            updated_by=actor_id,
        )
        for sequence_number, movement in enumerate(statement.movements, start=1)
    ]


def _statement(
    root: BankStatementModel,
    movements: tuple[BankMovementModel, ...],
) -> BankStatement:
    return BankStatement(
        id=root.id,
        company_id=root.company_id,
        bank_account_id=root.bank_account_id,
        bank_code=root.bank_code,
        account_reference=root.account_reference,
        period_start=root.period_start,
        period_end=root.period_end,
        imported_at=root.imported_at,
        source=BankStatementSource(root.source),
        source_hash=root.source_hash,
        movements=tuple(_movement(value) for value in movements),
        opening_balance=root.opening_balance,
        closing_balance=root.closing_balance,
        version=root.version,
    )


def _movement(model: BankMovementModel) -> BankMovement:
    return BankMovement(
        id=model.id,
        company_id=model.company_id,
        bank_account_id=model.bank_account_id,
        external_id=model.external_id,
        booked_on=model.booked_on,
        amount=model.amount,
        direction=BankMovementDirection(model.direction),
        kind=BankTransactionKind(model.kind),
        description=model.description,
        document_number=model.document_number,
        status=BankMovementStatus(model.status),
        matched_reference_id=model.matched_reference_id,
        reconciled_at=model.reconciled_at,
        match_score=model.match_score,
    )


def _validate_frozen_statement(current: BankStatement, candidate: BankStatement) -> None:
    current_movements = {value.id: value for value in current.movements}
    candidate_movements = {value.id: value for value in candidate.movements}
    if (
        current.id != candidate.id
        or current.company_id != candidate.company_id
        or current.bank_account_id != candidate.bank_account_id
        or current.bank_code != candidate.bank_code
        or current.account_reference != candidate.account_reference
        or current.period_start != candidate.period_start
        or current.period_end != candidate.period_end
        or current.imported_at != candidate.imported_at
        or current.source != candidate.source
        or current.source_hash != candidate.source_hash
        or current.opening_balance != candidate.opening_balance
        or current.closing_balance != candidate.closing_balance
        or current_movements.keys() != candidate_movements.keys()
    ):
        raise InvalidBankStatementError("Imported bank-statement snapshots are immutable.")
    for movement_id, previous in current_movements.items():
        proposed = candidate_movements[movement_id]
        if _movement_identity(previous) != _movement_identity(proposed):
            raise InvalidBankStatementError("Imported bank-movement snapshots are immutable.")


def _movement_identity(movement: BankMovement) -> tuple[object, ...]:
    return (
        movement.id,
        movement.company_id,
        movement.bank_account_id,
        movement.external_id,
        movement.booked_on,
        movement.amount,
        movement.direction,
        movement.kind,
        movement.description,
        movement.document_number,
    )


def _reconciliation_changes(
    current: BankStatement,
    candidate: BankStatement,
) -> tuple[BankMovement, ...]:
    previous = {value.id: value for value in current.movements}
    changed: list[BankMovement] = []
    for movement in candidate.movements:
        old = previous[movement.id]
        if old == movement:
            continue
        if (
            old.status is not BankMovementStatus.PENDING
            or movement.status is not BankMovementStatus.RECONCILED
        ):
            raise InvalidBankStatementError(
                "Only pending movements may gain reconciliation evidence."
            )
        changed.append(movement)
    if not changed:
        raise InvalidBankStatementError("save requires a reconciliation change.")
    return tuple(changed)


def _nonzero_uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field} must be a non-zero UUID.")
    return value


def _source_hash(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("source_hash must be text.")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError("source_hash must be a SHA-256 hexadecimal digest.")
    return normalized


def _import_metadata(original_file_name: str | None, file_size_bytes: int) -> None:
    if original_file_name is not None and (
        not isinstance(original_file_name, str)
        or not original_file_name.strip()
        or len(original_file_name) > 255
    ):
        raise ValueError("original_file_name must contain between 1 and 255 characters.")
    if type(file_size_bytes) is not int or file_size_bytes < 0:
        raise ValueError("file_size_bytes must be a non-negative integer.")


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["BankStatementRepository"]
