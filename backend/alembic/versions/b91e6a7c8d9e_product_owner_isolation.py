"""add product owner isolation

Revision ID: b91e6a7c8d9e
Revises: f7b1c2d3e4f5
Create Date: 2026-08-03 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b91e6a7c8d9e"
down_revision: Union[str, None] = "f7b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_OWNER = "local:local-dev"


def upgrade() -> None:
    # Existing local workspaces remain accessible to the legacy local identity.
    # New records receive their owner from the authenticated product principal.
    with op.batch_alter_table("repositories") as batch_op:
        batch_op.add_column(
            sa.Column(
                "owner_id",
                sa.String(length=320),
                nullable=False,
                server_default=_LEGACY_OWNER,
            )
        )
        batch_op.create_index("ix_repositories_owner_id", ["owner_id"], unique=False)
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "owner_id",
                sa.String(length=320),
                nullable=False,
                server_default=_LEGACY_OWNER,
            )
        )
        batch_op.create_index("ix_agent_runs_owner_id", ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_index("ix_agent_runs_owner_id")
        batch_op.drop_column("owner_id")
    with op.batch_alter_table("repositories") as batch_op:
        batch_op.drop_index("ix_repositories_owner_id")
        batch_op.drop_column("owner_id")
