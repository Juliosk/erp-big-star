"""Executable compliance contract for the Triple Track operational runbooks."""

from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs"


@dataclass(frozen=True, slots=True)
class RunbookContract:
    path: Path
    api: str
    ui: str
    read_permission: str
    track_guards: tuple[str, ...]


RUNBOOKS = (
    RunbookContract(
        path=DOCS_ROOT / "fiscal-runbook.md",
        api="/api/v1/fiscal/cockpit",
        ui="/ui/fiscal/cockpit",
        read_permission="fiscal.tax_rule.read",
        track_guards=("fiscal.tax_rule.activate", "SEFAZ", "snapshots tributários"),
    ),
    RunbookContract(
        path=DOCS_ROOT / "procurement-runbook.md",
        api="/api/v1/procurement/cockpit",
        ui="/ui/procurement/cockpit",
        read_permission="procurement.rfq.read",
        track_guards=(
            "procurement.rfq.manage",
            "procurement.rfq.award",
            "SOD_VIOLATION",
            "conversão cambial implícita",
        ),
    ),
    RunbookContract(
        path=DOCS_ROOT / "treasury-runbook.md",
        api="/api/v1/finance/cockpit",
        ui="/ui/finance/cockpit",
        read_permission="finance.treasury.read",
        track_guards=(
            "finance.payment.request",
            "finance.payment.approve",
            "SOD_VIOLATION",
            "confirmação bancária",
        ),
    ),
)

QUALITY_GATE_COMMANDS = (
    "alembic upgrade head",
    "alembic current",
    "alembic check",
    "ruff check erp tests migrations",
    "mypy erp tests migrations",
    "pytest --import-mode=importlib",
)

COMMON_OPERATIONAL_CONTRACT = (
    "## Fechamento operacional da Trilha Tripla — Commit 221",
    "company_id",
    "somente leitura",
    "Cache-Control: no-store",
    "Audit",
    "Outbox",
    "apenas na memória da página",
    "403",
    "404",
    "503",
    "(triple-track-closure.md)",
)


@pytest.mark.parametrize("contract", RUNBOOKS, ids=lambda item: item.path.stem)
def test_runbook_preserves_the_operational_closure_contract(
    contract: RunbookContract,
) -> None:
    content = " ".join(contract.path.read_text(encoding="utf-8").casefold().split())

    required = (
        *COMMON_OPERATIONAL_CONTRACT,
        f"GET {contract.api}?company_id={{uuid}}",
        contract.ui,
        contract.read_permission,
        *contract.track_guards,
    )
    missing = [fragment for fragment in required if fragment.casefold() not in content]
    assert missing == [], f"{contract.path.name} is missing: {missing}"


def test_closure_report_links_the_runbooks_and_reproducible_quality_gates() -> None:
    report = (DOCS_ROOT / "triple-track-closure.md").read_text(encoding="utf-8")

    for contract in RUNBOOKS:
        assert contract.path.name in report
    for fragment in (
        "Migration 0061",
        "compare_metadata",
        *QUALITY_GATE_COMMANDS,
    ):
        assert fragment in report
