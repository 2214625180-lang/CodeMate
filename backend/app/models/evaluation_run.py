import uuid
from datetime import datetime

from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import UTCDateTime, utc_now
from app.core.database import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    dataset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    results = relationship(
        "Evaluation",
        back_populates="evaluation_run",
        cascade="all, delete-orphan",
        order_by="Evaluation.created_at",
    )
