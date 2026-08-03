from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"
    __table_args__ = (Index("ix_agent_checkpoints_thread_created", "thread_id", "created_at"),)

    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    checkpoint_ns: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_type: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class AgentCheckpointBlob(Base):
    __tablename__ = "agent_checkpoint_blobs"

    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    checkpoint_ns: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(255), primary_key=True)
    value_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class AgentCheckpointWrite(Base):
    __tablename__ = "agent_checkpoint_writes"

    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    checkpoint_ns: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    write_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    task_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
