"""Executable architectural boundaries for the complete M12 public surface."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
FINANCE_ROOT = PROJECT_ROOT / "erp" / "modules" / "finance"


def _imports(source: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def test_finance_contracts_and_domain_are_framework_free() -> None:
    forbidden = (
        "aio_pika",
        "asyncpg",
        "celery",
        "fastapi",
        "pydantic",
        "redis",
        "sqlalchemy",
        "erp.platform",
    )
    violations = []
    sources = [FINANCE_ROOT / "contracts.py", *sorted((FINANCE_ROOT / "domain").glob("*.py"))]
    for source in sources:
        for imported in _imports(source):
            if imported.startswith(forbidden):
                violations.append((source.name, imported))
    assert violations == []


def test_finance_does_not_import_procurement_or_fiscal_implementations() -> None:
    forbidden = ("erp.modules.procurement", "erp.modules.fiscal")
    violations = []
    for source in FINANCE_ROOT.rglob("*.py"):
        for imported in _imports(source):
            if imported.startswith(forbidden):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []
