"""strict agent verification statuses

Revision ID: e214d74a9c31
Revises: a83f51d7240e
Create Date: 2026-08-02 12:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e214d74a9c31"
down_revision: Union[str, None] = "a83f51d7240e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Legacy `success` runs lack mandatory pre-patch reproduction evidence.
    op.execute(
        "UPDATE agent_runs SET status = 'unverified_patch' WHERE status = 'success'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE agent_runs SET status = 'success' WHERE status = 'unverified_patch'"
    )
