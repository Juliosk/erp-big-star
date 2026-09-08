"""Company-owned templates with immutable, fingerprinted schema versions."""

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


class ImportCommitMode(StrEnum):
    ALL_OR_NOTHING = "ALL_OR_NOTHING"
    VALID_ROWS_ONLY = "VALID_ROWS_ONLY"
    BATCH_ATOMIC = "BATCH_ATOMIC"


def require_uuid(*values: UUID) -> None:
    if any(not isinstance(value, UUID) for value in values):
        raise ValueError("Identity and company scope must be explicit UUIDs.")


def require_positive(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError("Version must be a positive PostgreSQL integer.")


@dataclass(frozen=True, slots=True)
class ImportField:
    name: str
    required: bool

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name) is None:
            raise ValueError("Field name must be canonical snake_case, up to 64 characters.")
        if type(self.required) is not bool:
            raise ValueError("Field required must be a boolean.")


@dataclass(frozen=True, slots=True)
class ImportTemplate:
    id: UUID
    company_id: UUID
    code: str
    name: str
    target_domain: str = "product"

    def __post_init__(self) -> None:
        require_uuid(self.id, self.company_id)
        if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", self.code) is None:
            raise ValueError("Template code must be a canonical identifier.")
        if not 1 <= len(self.name) <= 200 or self.name != self.name.strip():
            raise ValueError("Template name must contain 1-200 trimmed characters.")
        if self.target_domain != "product":
            raise ValueError("Only the product target domain is enabled in this slice.")

    @classmethod
    def create(cls, *, company_id: UUID, code: str, name: str) -> ImportTemplate:
        return cls(uuid4(), company_id, code.strip().upper(), name.strip())


@dataclass(frozen=True, slots=True)
class ImportTemplateVersion:
    id: UUID
    company_id: UUID
    template_id: UUID
    number: int
    fields: tuple[ImportField, ...]
    allowed_modes: tuple[ImportCommitMode, ...]

    def __post_init__(self) -> None:
        require_uuid(self.id, self.company_id, self.template_id)
        require_positive(self.number)
        if (
            not isinstance(self.fields, tuple)
            or not 1 <= len(self.fields) <= 100
            or any(not isinstance(item, ImportField) for item in self.fields)
        ):
            raise ValueError("A template version requires 1-100 immutable field definitions.")
        if len({item.name for item in self.fields}) != len(self.fields):
            raise ValueError("Template fields must be unique.")
        if (
            not isinstance(self.allowed_modes, tuple)
            or not self.allowed_modes
            or any(not isinstance(mode, ImportCommitMode) for mode in self.allowed_modes)
            or len(set(self.allowed_modes)) != len(self.allowed_modes)
        ):
            raise ValueError("Commit modes must be explicit, supported, unique and immutable.")

    @property
    def fingerprint(self) -> str:
        """Stable schema identity; ordered fields matter, mode ordering does not."""
        encoded = json.dumps(
            {
                "fields": [{"name": item.name, "required": item.required} for item in self.fields],
                "allowed_modes": sorted(self.allowed_modes),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["ImportCommitMode", "ImportField", "ImportTemplate", "ImportTemplateVersion"]
