import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MCPServerRevision(Base):
    __tablename__ = "mcp_server_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("mcp_server_registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    server = relationship("MCPServerRegistration", back_populates="revisions")
