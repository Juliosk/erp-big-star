"""M5 public contracts export references without infrastructure coupling."""

from decimal import Decimal
from uuid import uuid4

from erp.modules.inventory.application.permissions import INVENTORY_BALANCE_READ
from erp.modules.inventory.contracts import InventoryBalanceReference


def test_public_contract_exports_balance_reference_and_read_permission() -> None:
    reference = InventoryBalanceReference(
        company_id=uuid4(),
        product_id=uuid4(),
        warehouse_id=uuid4(),
        location_id=None,
        lot_id=None,
        pool_id=uuid4(),
        state="AVAILABLE",
        on_hand=Decimal("12"),
        reserved=Decimal("2"),
        available=Decimal("10"),
        version=1,
    )

    assert str(INVENTORY_BALANCE_READ) == "inventory.balance.read"
    assert reference.available == Decimal("10")
