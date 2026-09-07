"""Create the platform and admin schemas.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only the two schemas approved for the W0 baseline."""
    op.execute(sa.schema.CreateSchema("platform", if_not_exists=True))
    op.execute(sa.schema.CreateSchema("admin", if_not_exists=True))


def downgrade() -> None:
    """Remove the empty W0 schemas in reverse ownership order."""
    op.execute(sa.schema.DropSchema("admin", if_exists=True))
    op.execute(sa.schema.DropSchema("platform", if_exists=True))
