import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MCPQuotaPolicy(Base):
    __tablename__ = "mcp_quota_policies"
    __table_args__ = (UniqueConstraint("scope_key", name="uq_mcp_quota_policy_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="*")
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False, default="*")
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, default="*")
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_call_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_cost_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    concurrent_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_call_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_run_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_cost_units: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    warning_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    temporary_override_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    temporary_override_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    charges = relationship("MCPQuotaCharge", cascade="all, delete-orphan")


class MCPQuotaEvent(Base):
    __tablename__ = "mcp_quota_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mcp_tool_executions.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repo_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    delegated_identity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    cost_units: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved", index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    charges = relationship("MCPQuotaCharge", cascade="all, delete-orphan")


class MCPQuotaCharge(Base):
    __tablename__ = "mcp_quota_charges"
    __table_args__ = (
        UniqueConstraint("event_id", "policy_id", name="uq_mcp_quota_charge_event_policy"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_quota_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    policy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_quota_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_units: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MCPQuotaRejection(Base):
    __tablename__ = "mcp_quota_rejections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    policy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mcp_quota_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    repo_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MCPQuotaReconciliation(Base):
    __tablename__ = "mcp_quota_reconciliations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    repaired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    drift_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
