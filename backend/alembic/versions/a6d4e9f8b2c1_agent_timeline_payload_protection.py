"""protect agent Timeline payloads

Revision ID: a6d4e9f8b2c1
Revises: e5c3a9f7d1b2
Create Date: 2026-08-04 15:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a6d4e9f8b2c1"
down_revision: Union[str, None] = "e5c3a9f7d1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agent_steps") as batch_op:
        batch_op.add_column(
            sa.Column(
                "input_classification",
                sa.String(length=32),
                nullable=False,
                server_default="metadata",
            )
        )
        batch_op.add_column(
            sa.Column(
                "output_classification",
                sa.String(length=32),
                nullable=False,
                server_default="metadata",
            )
        )
        batch_op.add_column(sa.Column("input_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("output_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("payload_expires_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_agent_steps_payload_expires_at", ["payload_expires_at"])

    # Existing JSON was stored without classification or encryption. Purge it
    # instead of attempting a migration-time re-encryption with deployment keys.
    op.execute(
        "UPDATE agent_steps SET input_json = NULL, output_json = NULL, "
        "input_classification = 'legacy_purged', output_classification = 'legacy_purged'"
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_steps") as batch_op:
        batch_op.drop_index("ix_agent_steps_payload_expires_at")
        batch_op.drop_column("payload_expires_at")
        batch_op.drop_column("output_encrypted")
        batch_op.drop_column("input_encrypted")
        batch_op.drop_column("output_classification")
        batch_op.drop_column("input_classification")
