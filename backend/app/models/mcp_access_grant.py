import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class MCPAccessGrant(Base):
    __tablename__ = "mcp_access_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, default="*", index=True)
    permissions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
