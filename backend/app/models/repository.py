import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("mcp_tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    memory_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    files = relationship("CodeFile", back_populates="repository", cascade="all, delete-orphan")
    chunks = relationship("CodeChunk", back_populates="repository", cascade="all, delete-orphan")
