import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import UTCDateTime, utc_now


class GitHubAppRepair(Base):
    __tablename__ = "github_app_repairs"
    __table_args__ = (
        UniqueConstraint("repo_id", "workflow_run_id", name="uq_github_app_repair_workflow_run"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    failure_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="fixing", index=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
