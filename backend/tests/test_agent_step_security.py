import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.agent_step_service import AgentStepService


def test_restricted_timeline_payloads_are_redacted_encrypted_and_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mcp_registry_kms_provider", "local")
    monkeypatch.setattr(settings, "mcp_registry_master_key", "timeline-test-key-32-characters-long")
    monkeypatch.setattr(settings, "mcp_registry_previous_master_key", None)
    monkeypatch.setattr(settings, "agent_timeline_sensitive_retention_hours", 1)
    engine = create_engine(f"sqlite:///{tmp_path / 'timeline.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-timeline",
        name="timeline",
        repo_url="https://example.com/timeline.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-timeline",
        repo_id=repository.id,
        user_input="fix the failing test",
        status="running",
    )
    db.add_all([repository, run])
    db.commit()

    secret = "timeline-secret-value"
    service = AgentStepService(db)
    step = service.record(
        run_id=run.id,
        step_type="tool_result",
        input_json={"diff_preview": f"API_TOKEN={secret}"},
        output_json={
            "stdout": f"failed with token {secret}",
            "status": "completed",
            "exit_code": 1,
        },
    )

    stored = json.dumps({"input": step.input_json, "output": step.output_json})
    assert secret not in stored
    assert step.input_classification == "restricted"
    assert step.output_classification == "restricted"
    assert step.input_encrypted is not None and secret not in step.input_encrypted
    assert step.output_encrypted is not None and secret not in step.output_encrypted
    assert step.output_json["status"]["redacted"] is True
    assert service.restricted_dict(step)["input_json"] == {
        "diff_preview": f"API_TOKEN={secret}"
    }
    assert service.restricted_dict(step)["output_json"] == {
        "stdout": f"failed with token {secret}",
        "status": "completed",
        "exit_code": 1,
    }

    step.payload_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.add(step)
    db.commit()
    assert service.purge_expired_payloads() == 1
    db.refresh(step)
    assert step.input_encrypted is None
    assert step.output_encrypted is None
    assert step.payload_expires_at is None
    db.close()


def test_restricted_timeline_preserves_scalar_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mcp_registry_kms_provider", "local")
    monkeypatch.setattr(settings, "mcp_registry_master_key", "timeline-test-key-32-characters-long")
    engine = create_engine(f"sqlite:///{tmp_path / 'timeline-scalar.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-timeline-scalar",
        name="timeline-scalar",
        repo_url="https://example.com/timeline-scalar.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-timeline-scalar",
        repo_id=repository.id,
        user_input="fix the failing test",
        status="running",
    )
    db.add_all([repository, run])
    db.commit()

    step = AgentStepService(db).record(
        run_id=run.id,
        step_type="tool_result",
        output_json="scalar-secret-output",
    )

    assert step.output_json["redacted"] is True
    assert AgentStepService(db).restricted_dict(step)["output_json"] == "scalar-secret-output"
    db.close()
