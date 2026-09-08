"""Import registration is metadata, not permission to create master data."""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.governance.domain.import_template import (
    ImportCommitMode,
    require_positive,
    require_uuid,
)

MAX_SOURCE_BYTES = 10 * 1024 * 1024


class ImportJobStatus(StrEnum):
    UPLOADED = "UPLOADED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ImportJob:
    id: UUID
    company_id: UUID
    template_id: UUID
    template_version: int
    commit_mode: ImportCommitMode
    original_filename: str
    source_sha256: str
    source_size_bytes: int
    storage_key: str
    status: ImportJobStatus = ImportJobStatus.UPLOADED
    version: int = 1

    def __post_init__(self) -> None:
        require_uuid(self.id, self.company_id, self.template_id)
        require_positive(self.template_version)
        require_positive(self.version)
        if not isinstance(self.commit_mode, ImportCommitMode):
            raise ValueError("An explicit supported commit mode is required.")
        if not isinstance(self.status, ImportJobStatus):
            raise ValueError("Unsupported import job status.")
        if (
            not 6 <= len(self.original_filename) <= 255
            or self.original_filename != self.original_filename.strip()
            or not self.original_filename.lower().endswith(".xlsx")
            or re.search(r"[\\/:\x00-\x1f\x7f]", self.original_filename)
        ):
            raise ValueError("Source filename must be a plain XLSX filename, up to 255 characters.")
        if re.fullmatch(r"[a-f0-9]{64}", self.source_sha256) is None:
            raise ValueError("Source checksum must be lowercase SHA-256.")
        if (
            type(self.source_size_bytes) is not int
            or not 1 <= self.source_size_bytes <= MAX_SOURCE_BYTES
        ):
            raise ValueError("Source size must be an integer between 1 byte and 10 MiB.")
        if self.storage_key != self.expected_storage_key(self.company_id, self.id):
            raise ValueError("Storage key must be scoped to this company and job.")

    @staticmethod
    def expected_storage_key(company_id: UUID, job_id: UUID) -> str:
        return f"governance/{company_id}/imports/{job_id}/source.xlsx"

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        template_id: UUID,
        template_version: int,
        commit_mode: ImportCommitMode,
        original_filename: str,
        source_sha256: str,
        source_size_bytes: int,
    ) -> ImportJob:
        job_id = uuid4()
        return cls(
            job_id,
            company_id,
            template_id,
            template_version,
            commit_mode,
            original_filename.strip(),
            source_sha256,
            source_size_bytes,
            cls.expected_storage_key(company_id, job_id),
        )

    def cancel(self) -> ImportJob:
        """Only uploaded, unprocessed jobs may be cancelled in the foundation slice."""
        if self.status is not ImportJobStatus.UPLOADED:
            raise ValueError("Only an uploaded job can be cancelled.")
        return replace(self, status=ImportJobStatus.CANCELLED, version=self.version + 1)


__all__ = ["MAX_SOURCE_BYTES", "ImportJob", "ImportJobStatus"]
