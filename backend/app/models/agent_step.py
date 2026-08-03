import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, JSON, String
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
    input_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)

    run = relationship("AgentRun", back_populates="steps")
