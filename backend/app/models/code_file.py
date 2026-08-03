import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class CodeFile(Base):
    __tablename__ = "code_files"
    __table_args__ = (UniqueConstraint("repo_id", "file_path", name="uq_code_files_repo_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imports: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exports: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    repository = relationship("Repository", back_populates="files")
    chunks = relationship("CodeChunk", back_populates="file", cascade="all, delete-orphan")
