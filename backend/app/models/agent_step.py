import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    input_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="metadata")
    output_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="metadata")
    input_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)

    run = relationship("AgentRun", back_populates="steps")
