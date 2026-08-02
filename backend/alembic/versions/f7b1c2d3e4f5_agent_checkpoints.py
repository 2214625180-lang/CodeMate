"""persistent LangGraph agent checkpoints

Revision ID: f7b1c2d3e4f5
Revises: e214d74a9c31
Create Date: 2026-08-02 16:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7b1c2d3e4f5"
down_revision: Union[str, None] = "e214d74a9c31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_checkpoints",
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=255), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_type", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_blob", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_type", sa.String(length=64), nullable=False),
        sa.Column("metadata_blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_index(
        "ix_agent_checkpoints_thread_created",
        "agent_checkpoints",
        ["thread_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "agent_checkpoint_blobs",
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("value_type", sa.String(length=64), nullable=False),
        sa.Column("value_blob", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "channel", "version"),
    )
    op.create_table(
        "agent_checkpoint_writes",
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=255), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("write_index", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=255), nullable=False),
        sa.Column("value_type", sa.String(length=64), nullable=False),
        sa.Column("value_blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "write_index"
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_checkpoint_writes")
    op.drop_table("agent_checkpoint_blobs")
    op.drop_index("ix_agent_checkpoints_thread_created", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
