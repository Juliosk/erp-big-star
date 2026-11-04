"""Executable boundaries for the Production bounded context."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PRODUCTION_ROOT = PROJECT_ROOT / "erp" / "modules" / "production"


def _imports(source: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def test_production_domain_is_framework_and_cross_context_free() -> None:
    forbidden = (
        "aio_pika",
        "celery",
        "fastapi",
        "pydantic",
        "redis",
        "sqlalchemy",
        "erp.platform",
        "erp.modules.admin.",
        "erp.modules.product.",
        "erp.modules.inventory.",
        "erp.modules.procurement.",
        "erp.modules.workflow.",
    )
    violations = []
    for source in sorted((PRODUCTION_ROOT / "domain").glob("*.py")):
        for imported in _imports(source):
            if imported.startswith(forbidden):
                violations.append((source.name, imported))
    assert violations == []


def test_production_application_does_not_import_framework_or_adapter_layers() -> None:
    forbidden = ("fastapi", "pydantic", "sqlalchemy")
    violations = []
    for source in sorted((PRODUCTION_ROOT / "application").glob("*.py")):
        for imported in _imports(source):
            if imported.startswith(forbidden) or ".api" in imported or ".infrastructure" in imported:
                violations.append((source.name, imported))
    assert violations == []

