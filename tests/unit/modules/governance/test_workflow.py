from dataclasses import replace

import pytest

from erp.modules.governance.domain import ImportCommitMode, ImportJobStatus
from erp.modules.governance.domain.workflow import advance
from tests.unit.modules.governance.test_import_foundation import job


@pytest.mark.parametrize("mode", [ImportCommitMode.VALID_ROWS_ONLY, ImportCommitMode.BATCH_ATOMIC])
def test_future_modes_are_not_operational(mode: ImportCommitMode) -> None:
    with pytest.raises(ValueError, match="ALL_OR_NOTHING"):
        advance(replace(job(), commit_mode=mode), ImportJobStatus.VALIDATED)


def test_strict_state_machine_has_no_implicit_commit_or_post_commit_mutation() -> None:
    current = job()
    with pytest.raises(ValueError, match="transition"):
        advance(current, ImportJobStatus.COMMITTED)
    for state in (
        ImportJobStatus.VALIDATED,
        ImportJobStatus.PREVIEWED,
        ImportJobStatus.CONFIRMED,
        ImportJobStatus.COMMITTED,
    ):
        current = advance(current, state)
    assert current.version == 5
    with pytest.raises(ValueError, match="transition"):
        advance(current, ImportJobStatus.CANCELLED)
