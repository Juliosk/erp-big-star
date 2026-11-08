"""Compliance checks for the Production operational closure evidence."""

from pathlib import Path

RUNBOOK = Path("docs/production-runbook.md")


def test_production_runbook_covers_the_closed_operational_surface() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    required_contracts = (
        "ADR 0192",
        "BOM multinível",
        "MRP determinístico",
        "reserva de produção `HARD`",
        "ShopFloorExecutionService",
        "FOR UPDATE SKIP LOCKED",
        "ProductionOrderReleased",
        "ProductionOrderCompleted",
        "OperationCompleted",
        "MaterialConsumed",
        "ScrapRecorded",
        "InventoryAdjusted",
        "ProductUpdated",
        "BillOfMaterialsUpdated",
        "RoutingUpdated",
        "/api/v1/production/cockpit",
        "/ui/production/cockpit",
        "production.shop_floor.read",
        "0051",
        "0052",
        "0053",
        "0054",
        "0055",
        "0056",
    )
    assert all(value in content for value in required_contracts)


def test_production_runbook_preserves_safety_and_next_slice_boundaries() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    assert "docker system prune -a --volumes" in content
    assert "Nunca execute factory reset" in content
    assert "Vendas/Marketplaces" in content
    assert "WMS/Estoque" in content
    assert "adaptadores de marketplace não" in content
    assert "podem importar repositórios internos" in content


__all__: list[str] = []
