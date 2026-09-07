from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_configuration() -> dict[str, Any]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as configuration_file:
        return tomllib.load(configuration_file)


def test_project_metadata_declares_python_baseline() -> None:
    project = _project_configuration()["project"]

    assert project["name"] == "erp-bigstar"
    assert project["requires-python"] == ">=3.14,<3.15"


def test_runtime_dependencies_are_version_pinned() -> None:
    project = _project_configuration()["project"]

    assert project["dependencies"]
    assert all("==" in dependency for dependency in project["dependencies"])
