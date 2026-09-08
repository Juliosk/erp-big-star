"""Pure M23 invariants, deterministic fingerprints and immutable snapshots."""

from dataclasses import FrozenInstanceError, replace
from typing import Any
from uuid import uuid4

import pytest

from erp.modules.governance.domain import (
    ImportCommitMode,
    ImportField,
    ImportJob,
    ImportJobStatus,
    ImportTemplate,
    ImportTemplateVersion,
)


def template_version() -> ImportTemplateVersion:
    return ImportTemplateVersion(
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        (ImportField("code", True), ImportField("sku", True)),
        (ImportCommitMode.ALL_OR_NOTHING,),
    )


def job() -> ImportJob:
    return ImportJob.create(
        company_id=uuid4(),
        template_id=uuid4(),
        template_version=1,
        commit_mode=ImportCommitMode.ALL_OR_NOTHING,
        original_filename="Products.xlsx",
        source_sha256="a" * 64,
        source_size_bytes=100,
    )


def test_template_is_company_owned_canonical_and_frozen() -> None:
    template = ImportTemplate.create(company_id=uuid4(), code=" product-v1 ", name=" Products ")
    assert template.code == "PRODUCT-V1"
    assert template.name == "Products"
    assert template.target_domain == "product"
    with pytest.raises(FrozenInstanceError):
        template.name = "changed"  # type: ignore[misc]  # Exercise runtime frozen enforcement.


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "invalid"},
        {"company_id": None},
        {"code": "lowercase"},
        {"code": "A" * 65},
        {"name": " "},
        {"name": "A" * 201},
        {"target_domain": "inventory"},
    ],
)
def test_invalid_template_is_rejected(changes: dict[str, Any]) -> None:
    template = ImportTemplate.create(company_id=uuid4(), code="T1", name="Products")
    with pytest.raises(ValueError, match=r"UUID|Template|product"):
        replace(template, **changes)


@pytest.mark.parametrize(("name", "required"), [("Bad Field", True), ("", True), ("code", 1)])
def test_invalid_fields_are_rejected(name: str, required: Any) -> None:
    with pytest.raises(ValueError, match="Field"):
        ImportField(name, required)


def test_template_fingerprint_is_deterministic_and_sensitive_to_schema() -> None:
    original = template_version()
    assert len(original.fingerprint) == 64
    assert replace(original, id=uuid4()).fingerprint == original.fingerprint
    assert (
        replace(original, fields=tuple(reversed(original.fields))).fingerprint
        != original.fingerprint
    )
    modes = replace(original, allowed_modes=tuple(ImportCommitMode))
    assert (
        modes.fingerprint
        == replace(modes, allowed_modes=tuple(reversed(modes.allowed_modes))).fingerprint
    )
    assert modes.fingerprint != original.fingerprint
    with pytest.raises(FrozenInstanceError):
        original.fields = ()  # type: ignore[misc]  # Exercise runtime frozen enforcement.


@pytest.mark.parametrize(
    "changes",
    [
        {"number": 0},
        {"number": True},
        {"number": 2_147_483_648},
        {"template_id": "bad"},
        {"fields": ()},
        {"fields": []},
        {"fields": ("code",)},
        {"fields": (ImportField("code", True),) * 2},
        {"fields": tuple(ImportField(f"field_{index}", True) for index in range(101))},
        {"allowed_modes": ()},
        {"allowed_modes": []},
        {"allowed_modes": ("invalid",)},
        {"allowed_modes": (ImportCommitMode.ALL_OR_NOTHING,) * 2},
    ],
)
def test_invalid_template_version_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"Version|UUID|template|Template|Commit"):
        replace(template_version(), **changes)


def test_upload_metadata_and_cancellation_are_immutable() -> None:
    original = job()
    cancelled = original.cancel()
    assert original.status is ImportJobStatus.UPLOADED
    assert original.version == 1
    assert cancelled.status is ImportJobStatus.CANCELLED
    assert cancelled.version == 2
    assert str(original.company_id) in original.storage_key
    assert str(original.id) in original.storage_key
    with pytest.raises(ValueError, match="uploaded"):
        cancelled.cancel()


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 0},
        {"commit_mode": "unknown"},
        {"status": "COMMITTED"},
        {"original_filename": "../products.xlsx"},
        {"original_filename": "C:\\products.xlsx"},
        {"original_filename": "products.csv"},
        {"original_filename": "products.xlsx "},
        {"original_filename": "bad\x00.xlsx"},
        {"original_filename": "A" * 251 + ".xlsx"},
        {"source_sha256": "A" * 64},
        {"source_sha256": "a" * 63},
        {"source_size_bytes": 0},
        {"source_size_bytes": 10 * 1024 * 1024 + 1},
        {"source_size_bytes": True},
        {"storage_key": "other-company/source.xlsx"},
    ],
)
def test_invalid_job_metadata_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"Version|mode|status|Source|Storage"):
        replace(job(), **changes)
