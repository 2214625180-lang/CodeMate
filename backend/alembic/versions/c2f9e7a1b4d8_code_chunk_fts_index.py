"""add code chunk full text search index

Revision ID: c2f9e7a1b4d8
Revises: b91e6a7c8d9e
Create Date: 2026-08-03 14:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c2f9e7a1b4d8"
down_revision: Union[str, None] = "b91e6a7c8d9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_code_chunks_fts ON code_chunks USING GIN (
            (
                setweight(to_tsvector('simple', coalesce(symbol_name, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(file_path, '')), 'B') ||
                setweight(to_tsvector('simple', coalesce(summary, '')), 'C') ||
                setweight(to_tsvector('simple', coalesce(content, '')), 'D')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_code_chunks_fts")
