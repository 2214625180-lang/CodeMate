import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MCPToolApproval(Base):
    __tablename__ = "mcp_tool_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    qualified_name: Mapped[str] = mapped_column(String(257), nullable=False)
    server_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    catalog_entry_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    checkpoint_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checkpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    run = relationship("AgentRun", back_populates="mcp_approvals")
    executions = relationship(
        "MCPToolExecution",
        back_populates="approval",
        order_by="MCPToolExecution.created_at",
    )
