from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_phase2_columns()


def ensure_phase2_columns() -> None:
    """Small local-dev migration bridge until Alembic is introduced."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "repositories" in table_names:
        _ensure_column(
            "repositories",
            "chunk_count",
            "chunk_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column("repositories", "memory_summary", "memory_summary TEXT")
        _ensure_column(
            "repositories",
            "memory_data",
            "memory_data JSON NOT NULL DEFAULT '{}'",
        )
        _ensure_column("repositories", "memory_updated_at", "memory_updated_at TIMESTAMP")

    if "code_chunks" in table_names:
        _ensure_column(
            "code_chunks",
            "imports",
            "imports JSON NOT NULL DEFAULT '[]'",
        )
        _ensure_column(
            "code_chunks",
            "exports",
            "exports JSON NOT NULL DEFAULT '[]'",
        )

    if "agent_runs" in table_names:
        _ensure_column("agent_runs", "feedback_status", "feedback_status VARCHAR(32)")
        _ensure_column("agent_runs", "feedback_note", "feedback_note TEXT")
        _ensure_column("agent_runs", "feedback_at", "feedback_at TIMESTAMP")

    if "evaluations" in table_names:
        _ensure_column("evaluations", "evaluation_run_id", "evaluation_run_id VARCHAR(36)")
        _ensure_column("evaluations", "case_id", "case_id VARCHAR(128)")
        _ensure_column("evaluations", "status", "status VARCHAR(32)")
        _ensure_column("evaluations", "latency_ms", "latency_ms INTEGER")
        _ensure_column("evaluations", "score", "score FLOAT")
        _ensure_column("evaluations", "failure_category", "failure_category VARCHAR(128)")
        _ensure_column("evaluations", "agent_run_id", "agent_run_id VARCHAR(36)")
        _ensure_column("evaluations", "provider", "provider VARCHAR(128)")
        _ensure_column("evaluations", "model", "model VARCHAR(128)")
        _ensure_column(
            "evaluations",
            "metadata_json",
            "metadata_json JSON NOT NULL DEFAULT '{}'",
        )

    if "evaluation_runs" in table_names:
        _ensure_column("evaluation_runs", "dataset_id", "dataset_id VARCHAR(36)")
        _ensure_column("evaluation_runs", "dataset_version", "dataset_version INTEGER")
        _ensure_column("evaluation_runs", "dataset_snapshot_id", "dataset_snapshot_id VARCHAR(36)")
        _ensure_column(
            "evaluation_runs",
            "request_json",
            "request_json JSON NOT NULL DEFAULT '{}'",
        )

    if "evaluation_datasets" in table_names:
        _ensure_column(
            "evaluation_datasets",
            "baseline_run_id",
            "baseline_run_id VARCHAR(36)",
        )
        _ensure_column(
            "evaluation_datasets",
            "gate_policy_json",
            "gate_policy_json JSON NOT NULL DEFAULT '{}'",
        )


def _ensure_column(table_name: str, column_name: str, column_ddl: str) -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_ddl}"))
