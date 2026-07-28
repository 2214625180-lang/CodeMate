import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MCPToolExecution(Base):
    __tablename__ = "mcp_tool_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("mcp_tool_approvals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    qualified_name: Mapped[str] = mapped_column(String(257), nullable=False)
    server_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    idempotency_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deduplication_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    checkpoint_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checkpoint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciliation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reconciled_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    run = relationship("AgentRun", back_populates="mcp_executions")
    approval = relationship("MCPToolApproval", back_populates="executions")
