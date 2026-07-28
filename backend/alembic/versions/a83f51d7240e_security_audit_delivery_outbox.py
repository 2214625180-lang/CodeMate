"""security audit delivery outbox

Revision ID: a83f51d7240e
Revises: d61724294075
Create Date: 2026-07-14 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a83f51d7240e"
down_revision: Union[str, None] = "d61724294075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_audit_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("sink", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("remote_receipt_json", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "sink", name="uq_security_audit_event_sink"),
    )
    for column in (
        "delivered_at",
        "event_id",
        "lease_expires_at",
        "lease_token",
        "next_attempt_at",
        "payload_sha256",
        "sink",
        "status",
    ):
        op.create_index(
            f"ix_security_audit_deliveries_{column}",
            "security_audit_deliveries",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(
        (
            "delivered_at",
            "event_id",
            "lease_expires_at",
            "lease_token",
            "next_attempt_at",
            "payload_sha256",
            "sink",
            "status",
        )
    ):
        op.drop_index(
            f"ix_security_audit_deliveries_{column}",
            table_name="security_audit_deliveries",
        )
    op.drop_table("security_audit_deliveries")
