"""Tenant-bound persistence for work centers and complete routings."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.domain import (
    EngineeringVersion,
    ProductionConflictError,
    ProductionRouting,
    ProductionScopeError,
    ProductionVersionConflictError,
    RoutingOperation,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)
from erp.modules.production.infrastructure.engineering_model import (
    RoutingHeaderModel,
    RoutingOperationModel,
    WorkCenterModel,
)


def _work_center(model: WorkCenterModel) -> WorkCenter:
    return WorkCenter(
        company_id=model.company_id,
        code=WorkCenterCode(model.code),
        capabilities=frozenset(model.capabilities),
        record_version=model.version,
    )


def _routing(
    header: RoutingHeaderModel,
    operations: tuple[RoutingOperationModel, ...],
) -> ProductionRouting:
    return ProductionRouting(
        company_id=header.company_id,
        product_id=header.product_id,
        version=EngineeringVersion(
            code=header.version_code,
            revision=header.engineering_revision,
            effective_from=header.effective_from,
            effective_until=header.effective_until,
        ),
        operations=tuple(
            RoutingOperation(
                sequence=operation.sequence,
                name=operation.name,
                work_center=WorkCenterConstraint(
                    company_id=operation.company_id,
                    allowed_centers=tuple(
                        WorkCenterCode(code) for code in operation.allowed_work_centers
                    ),
                    required_capabilities=frozenset(operation.required_capabilities),
                ),
                setup_minutes=operation.setup_minutes,
                run_minutes_per_unit=operation.run_minutes_per_unit,
            )
            for operation in operations
        ),
        record_version=header.version,
    )


class RoutingRepository:
    """Persist routings and their tenant-owned work-center references."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add_work_center(self, center: WorkCenter, *, actor_id: UUID) -> WorkCenter:
        self._validate_center(center, actor_id)
        if center.record_version != 1:
            raise ValueError("A new work center must start at record_version one.")
        self._session.add(
            WorkCenterModel(
                company_id=self._company_id,
                code=center.code.value,
                capabilities=sorted(center.capabilities),
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict()
        return center

    async def get_work_center(self, code: WorkCenterCode) -> WorkCenter | None:
        if not isinstance(code, WorkCenterCode):
            raise TypeError("code must be a WorkCenterCode.")
        model = await self._session.get(
            WorkCenterModel,
            {"company_id": self._company_id, "code": code.value},
            populate_existing=True,
        )
        return None if model is None else _work_center(model)

    async def save_work_center(
        self,
        center: WorkCenter,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> WorkCenter:
        self._validate_center(center, actor_id)
        self._validate_next_version(center.record_version, expected_version)
        result = await self._session.execute(
            update(WorkCenterModel)
            .where(
                WorkCenterModel.company_id == self._company_id,
                WorkCenterModel.code == center.code.value,
                WorkCenterModel.version == expected_version,
            )
            .values(
                capabilities=sorted(center.capabilities),
                version=center.record_version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(WorkCenterModel.code)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise ProductionVersionConflictError(expected_version)
        await self._flush_conflict()
        return center

    async def add(self, aggregate: ProductionRouting, *, actor_id: UUID) -> ProductionRouting:
        self._validate_routing(aggregate, actor_id)
        if aggregate.record_version != 1:
            raise ValueError("A new routing must start at record_version one.")
        await self._require_work_centers(aggregate)
        header_id = uuid4()
        self._session.add(
            RoutingHeaderModel(
                id=header_id,
                company_id=self._company_id,
                product_id=aggregate.product_id,
                version_code=aggregate.version.code,
                engineering_revision=aggregate.version.revision,
                effective_from=aggregate.version.effective_from,
                effective_until=aggregate.version.effective_until,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict()
        self._add_operations(header_id, aggregate.operations)
        await self._flush_conflict()
        return aggregate

    async def get(self, product_id: UUID, version_code: str) -> ProductionRouting | None:
        code = self._version_code(version_code)
        result = await self._session.scalars(
            select(RoutingHeaderModel)
            .where(
                RoutingHeaderModel.company_id == self._company_id,
                RoutingHeaderModel.product_id == product_id,
                RoutingHeaderModel.version_code == code,
            )
            .execution_options(populate_existing=True)
        )
        header = result.one_or_none()
        if header is None:
            return None
        return _routing(header, await self._operations(header.id))

    async def save(
        self,
        aggregate: ProductionRouting,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> ProductionRouting:
        self._validate_routing(aggregate, actor_id)
        self._validate_next_version(aggregate.record_version, expected_version)
        await self._require_work_centers(aggregate)
        result = await self._session.execute(
            update(RoutingHeaderModel)
            .where(
                RoutingHeaderModel.company_id == self._company_id,
                RoutingHeaderModel.product_id == aggregate.product_id,
                RoutingHeaderModel.version_code == aggregate.version.code,
                RoutingHeaderModel.version == expected_version,
            )
            .values(
                engineering_revision=aggregate.version.revision,
                effective_from=aggregate.version.effective_from,
                effective_until=aggregate.version.effective_until,
                version=aggregate.record_version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(RoutingHeaderModel.id)
            .execution_options(synchronize_session=False)
        )
        header_id = result.scalar_one_or_none()
        if header_id is None:
            raise ProductionVersionConflictError(expected_version)
        await self._session.execute(
            delete(RoutingOperationModel).where(
                RoutingOperationModel.company_id == self._company_id,
                RoutingOperationModel.routing_id == header_id,
            )
        )
        self._add_operations(header_id, aggregate.operations)
        await self._flush_conflict()
        return aggregate

    async def _operations(self, header_id: UUID) -> tuple[RoutingOperationModel, ...]:
        result = await self._session.scalars(
            select(RoutingOperationModel)
            .where(
                RoutingOperationModel.company_id == self._company_id,
                RoutingOperationModel.routing_id == header_id,
            )
            .order_by(RoutingOperationModel.sequence)
            .execution_options(populate_existing=True)
        )
        return tuple(result)

    async def _require_work_centers(self, aggregate: ProductionRouting) -> None:
        codes = {
            code.value
            for operation in aggregate.operations
            for code in operation.work_center.allowed_centers
        }
        persisted = set(
            await self._session.scalars(
                select(WorkCenterModel.code).where(
                    WorkCenterModel.company_id == self._company_id,
                    WorkCenterModel.code.in_(codes),
                )
            )
        )
        if persisted != codes:
            raise ProductionConflictError(
                "Routing references a missing work center in the selected company."
            )

    def _add_operations(
        self,
        header_id: UUID,
        operations: tuple[RoutingOperation, ...],
    ) -> None:
        self._session.add_all(
            [
                RoutingOperationModel(
                    id=uuid4(),
                    company_id=self._company_id,
                    routing_id=header_id,
                    sequence=operation.sequence,
                    name=operation.name,
                    setup_minutes=operation.setup_minutes,
                    run_minutes_per_unit=operation.run_minutes_per_unit,
                    allowed_work_centers=[
                        code.value for code in operation.work_center.allowed_centers
                    ],
                    required_capabilities=sorted(
                        operation.work_center.required_capabilities
                    ),
                    version=1,
                )
                for operation in operations
            ]
        )

    def _validate_center(self, center: WorkCenter, actor_id: UUID) -> None:
        if not isinstance(center, WorkCenter):
            raise TypeError("center must be a WorkCenter.")
        if center.company_id != self._company_id:
            raise ProductionScopeError("work center belongs to another company.")
        self._actor(actor_id)

    def _validate_routing(self, aggregate: ProductionRouting, actor_id: UUID) -> None:
        if not isinstance(aggregate, ProductionRouting):
            raise TypeError("aggregate must be a ProductionRouting.")
        if aggregate.company_id != self._company_id:
            raise ProductionScopeError("routing belongs to another company.")
        self._actor(actor_id)

    @staticmethod
    def _actor(actor_id: UUID) -> None:
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("actor_id must be a non-zero UUID.")

    @staticmethod
    def _validate_next_version(record_version: int, expected_version: int) -> None:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer.")
        if record_version != expected_version + 1:
            raise ValueError("save requires exactly one new record version.")

    @staticmethod
    def _version_code(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("version_code must be non-empty text.")
        return value.strip().upper()

    async def _flush_conflict(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise ProductionConflictError(
                    "Routing conflicts with a product, version, work center or tenant constraint."
                ) from error
            raise


__all__ = ["RoutingRepository", "_routing", "_work_center"]

