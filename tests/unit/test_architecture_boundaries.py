"""Executable import boundaries for every business-domain package."""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_FILES = sorted((PROJECT_ROOT / "erp" / "modules").glob("*/domain/**/*.py"))
FORBIDDEN_INFRASTRUCTURE_PREFIXES = (
    "celery",
    "fastapi",
    "httpx",
    "httpx2",
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
