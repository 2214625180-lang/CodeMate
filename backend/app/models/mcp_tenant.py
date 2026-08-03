import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class MCPTenant(Base):
    __tablename__ = "mcp_tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    memberships = relationship("MCPTenantMembership", cascade="all, delete-orphan")
    bindings = relationship("MCPTenantServerBinding", cascade="all, delete-orphan")
    grants = relationship("MCPAccessGrant", cascade="all, delete-orphan")
