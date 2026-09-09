"""Operational transitions. Optional future commit modes remain disabled."""

from dataclasses import replace

from erp.modules.governance.domain.import_job import ImportJob, ImportJobStatus
from erp.modules.governance.domain.import_template import ImportCommitMode


def advance(job: ImportJob, target: ImportJobStatus) -> ImportJob:
    if job.commit_mode is not ImportCommitMode.ALL_OR_NOTHING:
        raise ValueError("Only ALL_OR_NOTHING is operational.")
    editable = {
        ImportJobStatus.UPLOADED,
        ImportJobStatus.REJECTED,
        ImportJobStatus.VALIDATED,
        ImportJobStatus.PREVIEWED,
        ImportJobStatus.CONFIRMED,
    }
    allowed = (
        job.status in editable
        and target
        in {ImportJobStatus.VALIDATED, ImportJobStatus.REJECTED, ImportJobStatus.CANCELLED}
    ) or (job.status, target) in {
        (ImportJobStatus.VALIDATED, ImportJobStatus.PREVIEWED),
        (ImportJobStatus.PREVIEWED, ImportJobStatus.CONFIRMED),
        (ImportJobStatus.CONFIRMED, ImportJobStatus.COMMITTED),
    }
    if not allowed:
        raise ValueError("Invalid import job transition.")
    return replace(job, status=target, version=job.version + 1)


__all__ = ["advance"]
