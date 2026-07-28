import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MCPCredential(Base):
    __tablename__ = "mcp_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("mcp_server_registrations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    server = relationship("MCPServerRegistration", back_populates="credential")
