import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class MCPServerRegistration(Base):
    __tablename__ = "mcp_server_registrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    allowed_tools_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tool_policies_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    agent_context_tools_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    idempotency_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unvalidated", index=True
    )
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    server_info_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    capabilities_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tools_snapshot_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    credential = relationship(
        "MCPCredential",
        back_populates="server",
        cascade="all, delete-orphan",
        uselist=False,
    )
    revisions = relationship(
        "MCPServerRevision",
        back_populates="server",
        cascade="all, delete-orphan",
        order_by="MCPServerRevision.created_at.desc()",
    )
