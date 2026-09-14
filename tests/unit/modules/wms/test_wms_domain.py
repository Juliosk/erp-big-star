"""Pure M10 WMS domain invariants."""

from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.wms.domain import Package, PickingTask, PickingWave, Shipment


def test_picking_wave_release_is_versioned_and_restricted_to_draft() -> None:
    actor_id = uuid4()
    wave = PickingWave.create(company_id=uuid4(), code="web-001")

    released = wave.release(actor_id=actor_id)

    assert wave.code == "WEB-001"
    assert released.status == "RELEASED"
    assert released.released_by == actor_id
    assert released.version == 2
    with pytest.raises(ValueError, match="draft"):
        released.release(actor_id=actor_id)


def test_picking_task_scans_without_over_picking() -> None:
    task = PickingTask.create(
        company_id=uuid4(),
        wave_id=uuid4(),
        product_id=uuid4(),
        requested_quantity="3.000000",
    )

    partial = task.scan("1.25")
    completed = partial.scan(Decimal("1.750000"))

    assert partial.status == "IN_PROGRESS"
    assert partial.picked_quantity == Decimal("1.250000")
    assert completed.status == "COMPLETED"
    assert completed.picked_quantity == Decimal("3.000000")
    with pytest.raises(ValueError, match="exceed"):
        completed.scan("0.000001")


def test_package_requires_verify_before_finalize() -> None:
    package = Package.create(company_id=uuid4(), package_code="pkg-1")

    with pytest.raises(ValueError, match="verified"):
        package.finalize()
    assert package.verify().finalize().status == "FINALIZED"


def test_shipment_dispatch_requires_ready_state() -> None:
    shipment = Shipment.create(company_id=uuid4(), shipment_code="ship-1")

    with pytest.raises(ValueError, match="ready"):
        shipment.dispatch()
    dispatched = shipment.mark_ready().dispatch(tracking_code="trk-1")
    assert dispatched.status == "DISPATCHED"
    assert dispatched.tracking_code == "TRK-1"
