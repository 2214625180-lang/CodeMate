import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    case_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    repo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_lines: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)

    evaluation_run = relationship("EvaluationRun", back_populates="results")
