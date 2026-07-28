import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EvaluationDatasetSnapshot(Base):
    __tablename__ = "evaluation_dataset_snapshots"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_evaluation_dataset_snapshot_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    baseline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gate_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cases_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
