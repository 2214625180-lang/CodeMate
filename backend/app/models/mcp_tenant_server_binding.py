import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MCPTenantServerBinding(Base):
    __tablename__ = "mcp_tenant_server_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "server_name", name="uq_mcp_tenant_server"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
