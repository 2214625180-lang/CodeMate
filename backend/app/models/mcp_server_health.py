from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MCPServerHealth(Base):
    __tablename__ = "mcp_server_health"

    server_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    public_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    circuit_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="closed", index=True
    )
    manual_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_transport_successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_transport_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_rejections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_open_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_probes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_probes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_probe_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", index=True
    )
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    server_info_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    half_open_trial_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    half_open_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
