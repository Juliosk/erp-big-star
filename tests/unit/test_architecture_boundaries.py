"""Executable import boundaries for every business-domain package."""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_FILES = sorted((PROJECT_ROOT / "erp" / "modules").glob("*/domain/**/*.py"))
APPLICATION_FILES = sorted((PROJECT_ROOT / "erp" / "modules").glob("*/application/**/*.py"))
FORBIDDEN_INFRASTRUCTURE_PREFIXES = (
    "asyncpg",
    "celery",
    "fastapi",
    "httpx",
    "httpx2",
    "psycopg",
    "pydantic",
    "redis",
    "sqlalchemy",
    "erp.platform",
)


def imported_modules(source: str) -> Iterator[str]:
    """Yield absolute import targets from one Python source file."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module


@pytest.mark.parametrize("domain_file", DOMAIN_FILES, ids=lambda path: path.name)
def test_domain_imports_do_not_cross_infrastructure_boundaries(domain_file: Path) -> None:
    relative_parts = domain_file.relative_to(PROJECT_ROOT).parts
    owning_module = relative_parts[2]
    owning_prefix = f"erp.modules.{owning_module}."

    violations: list[str] = []
    for imported_module in imported_modules(domain_file.read_text(encoding="utf-8")):
        is_forbidden_technology = imported_module.startswith(FORBIDDEN_INFRASTRUCTURE_PREFIXES)
        is_cross_module = imported_module.startswith(
            "erp.modules."
        ) and not imported_module.startswith(owning_prefix)
        is_module_infrastructure = ".infrastructure" in imported_module
        if is_forbidden_technology or is_cross_module or is_module_infrastructure:
            violations.append(imported_module)

    assert violations == []


@pytest.mark.parametrize("application_file", APPLICATION_FILES, ids=lambda path: path.name)
def test_application_imports_do_not_depend_on_adapters_or_frameworks(
    application_file: Path,
) -> None:
    imported = imported_modules(application_file.read_text(encoding="utf-8"))
    forbidden_frameworks = ("aio_pika", "celery", "fastapi", "sqlalchemy")
    violations = [
        imported_module
        for imported_module in imported
        if imported_module.startswith(forbidden_frameworks)
        or ".api" in imported_module
        or ".infrastructure" in imported_module
    ]

    assert violations == []


def test_governance_imports_only_own_module_or_public_owner_contracts() -> None:
    """M23 cannot bypass M1/M2 by importing an owner's repositories or API internals."""
    allowed = (
        "erp.modules.governance.",
        "erp.modules.admin.contracts",
        "erp.modules.product.contracts",
    )
    violations = []
    for source in (PROJECT_ROOT / "erp" / "modules" / "governance").rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith("erp.modules.") and not imported.startswith(allowed):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []


def test_procurement_imports_only_own_module_or_public_owner_contracts() -> None:
    """M6 must integrate with other owners through explicit public contracts only."""
    allowed = (
        "erp.modules.procurement.",
        "erp.modules.admin.contracts",
        "erp.modules.product.contracts",
        "erp.modules.inventory.contracts",
        "erp.modules.workflow.contracts",
    )
    violations = []
    root = PROJECT_ROOT / "erp" / "modules" / "procurement"
    for source in root.rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith("erp.modules.") and not imported.startswith(allowed):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []


def test_procurement_never_depends_on_fiscal_or_finance_internals() -> None:
    """M11/M12 remain independent owners even after their packages are introduced."""
    forbidden = (
        "erp.modules.fiscal",
        "erp.modules.finance",
        "erp.modules.financial",
        "erp.modules.accounts_receivable",
        "erp.modules.accounts_payable",
    )
    violations = []
    root = PROJECT_ROOT / "erp" / "modules" / "procurement"
    for source in root.rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith(forbidden):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []


def test_fiscal_imports_only_own_module_or_public_owner_contracts() -> None:
    """M11 cannot bypass M6/M12 ownership through internal imports."""
    allowed = (
        "erp.modules.fiscal.",
        "erp.modules.admin.contracts",
    )
    violations = []
    root = PROJECT_ROOT / "erp" / "modules" / "fiscal"
    for source in root.rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith("erp.modules.") and not imported.startswith(allowed):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []


def test_fiscal_never_depends_on_procurement_or_finance_internals() -> None:
    forbidden = (
        "erp.modules.procurement",
        "erp.modules.finance",
        "erp.modules.financial",
        "erp.modules.accounts_payable",
        "erp.modules.accounts_receivable",
    )
    violations = []
    root = PROJECT_ROOT / "erp" / "modules" / "fiscal"
    for source in root.rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith(forbidden):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []


def test_finance_imports_only_own_module_or_public_admin_contracts() -> None:
    """M12 keeps its anti-corruption contracts independent from M11/M6 internals."""
    allowed = (
        "erp.modules.finance.",
        "erp.modules.admin.contracts",
    )
    violations = []
    root = PROJECT_ROOT / "erp" / "modules" / "finance"
    for source in root.rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith("erp.modules.") and not imported.startswith(allowed):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []


def test_finance_never_depends_on_procurement_or_fiscal_internals() -> None:
    """M12 receives translated facts and never reaches into M6/M11 implementations."""
    forbidden = (
        "erp.modules.procurement",
        "erp.modules.fiscal",
    )
    violations = []
    root = PROJECT_ROOT / "erp" / "modules" / "finance"
    for source in root.rglob("*.py"):
        for imported in imported_modules(source.read_text(encoding="utf-8")):
            if imported.startswith(forbidden):
                violations.append((str(source.relative_to(PROJECT_ROOT)), imported))
    assert violations == []
