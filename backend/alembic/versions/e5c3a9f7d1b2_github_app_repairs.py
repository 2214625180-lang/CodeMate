"""add GitHub App repair workflow records

Revision ID: e5c3a9f7d1b2
Revises: c2f9e7a1b4d8
Create Date: 2026-08-03 16:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5c3a9f7d1b2"
down_revision: Union[str, None] = "c2f9e7a1b4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_app_repairs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("repo_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_url", sa.Text(), nullable=True),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("failure_summary", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=320), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "workflow_run_id", name="uq_github_app_repair_workflow_run"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_github_app_repairs_repo_id", "github_app_repairs", ["repo_id"])
    op.create_index("ix_github_app_repairs_status", "github_app_repairs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_github_app_repairs_status", table_name="github_app_repairs")
    op.drop_index("ix_github_app_repairs_repo_id", table_name="github_app_repairs")
    op.drop_table("github_app_repairs")
