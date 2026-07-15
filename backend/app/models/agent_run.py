import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="fix")
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="agent")
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False, default="codemate-agent")
    delegated_identity_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mcp_delegated_identities.id", ondelete="SET NULL"), nullable=True
    )
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    test_command: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    final_diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feedback_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    repository = relationship("Repository")
    steps = relationship(
        "AgentStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.created_at",
    )
    mcp_approvals = relationship(
        "MCPToolApproval",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="MCPToolApproval.requested_at",
    )
    mcp_executions = relationship(
        "MCPToolExecution",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="MCPToolExecution.created_at",
    )
