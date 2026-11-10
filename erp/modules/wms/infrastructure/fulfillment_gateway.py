"""Session-bound WMS adapter that dispatches finalized physical packages."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.wms.contracts import OutboundShipmentReference
from erp.modules.wms.domain import PackageStatus, ShipmentStatus
from erp.modules.wms.infrastructure.wms_model import PackageModel, ShipmentModel
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


class SessionOutboundShipmentGateway:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def dispatch(
        self,
        *,
        company_id: UUID,
        shipment_id: UUID,
        expected_version: int,
        carrier_code: str,
        tracking_code: str,
        actor_id: UUID,
    ) -> OutboundShipmentReference:
        shipment = await self._session.scalar(
            select(ShipmentModel)
            .where(
                ShipmentModel.company_id == company_id,
                ShipmentModel.id == shipment_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if shipment is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="WMS shipment not found.",
                status_code=404,
            )
        if shipment.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        if shipment.status != ShipmentStatus.READY_TO_DISPATCH:
            raise ApplicationError(
                code="WMS_SHIPMENT_NOT_READY",
                message="WMS shipment is not ready for dispatch.",
                status_code=409,
            )
        packages = tuple(
            await self._session.scalars(
                select(PackageModel)
                .where(
                    PackageModel.company_id == company_id,
                    PackageModel.shipment_id == shipment_id,
                )
                .order_by(PackageModel.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if not packages or any(
            package.status != PackageStatus.FINALIZED for package in packages
        ):
            raise ApplicationError(
                code="WMS_SHIPMENT_NOT_PACKED",
                message="All WMS shipment packages must be finalized.",
                status_code=409,
            )
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(ShipmentModel)
            .where(
                ShipmentModel.company_id == company_id,
                ShipmentModel.id == shipment_id,
                ShipmentModel.version == expected_version,
                ShipmentModel.status == ShipmentStatus.READY_TO_DISPATCH,
            )
            .values(
                status=ShipmentStatus.DISPATCHED,
                carrier_code=carrier_code,
                tracking_code=tracking_code,
                dispatched_at=now,
                version=expected_version + 1,
                updated_by=actor_id,
            )
            .returning(ShipmentModel.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise OptimisticLockError(expected_version=expected_version)
        await self._session.execute(
            update(PackageModel)
            .where(
                PackageModel.company_id == company_id,
                PackageModel.shipment_id == shipment_id,
                PackageModel.status == PackageStatus.FINALIZED,
            )
            .values(
                status=PackageStatus.DISPATCHED,
                version=PackageModel.version + 1,
                updated_by=actor_id,
            )
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return OutboundShipmentReference(
            company_id=company_id,
            shipment_id=shipment_id,
            status=ShipmentStatus.DISPATCHED,
            carrier_code=carrier_code,
            tracking_code=tracking_code,
            dispatched_at=now,
            package_ids=tuple(package.id for package in packages),
            version=expected_version + 1,
        )


__all__ = ["SessionOutboundShipmentGateway"]
