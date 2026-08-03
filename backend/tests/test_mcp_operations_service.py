from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import queue as queue_module
from app.core.config import settings
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.mcp_execution_service import MCPExecutionService, execution_idempotency_key
from app.services.mcp_operations_service import (
    MCPCircuitConflictError,
    MCPCircuitOpenError,
    MCPOperationsService,
)


@pytest.fixture
def operations_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'operations.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-ops",
        name="repo",
        repo_url="https://example.com/repo.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-ops",
        repo_id=repository.id,
        user_input="operate",
        status="running",
    )
    db.add_all([repository, run])
    db.commit()
    monkeypatch.setattr(
        queue_module,
        "enqueue_mcp_execution_watchdog",
        lambda execution_id, version, delay_seconds: (
            f"watchdog-{execution_id}-{version}-{delay_seconds}"
        ),
    )
    yield db, run
    db.close()


def test_circuit_opens_rejects_and_recovers_through_half_open(operations_db, monkeypatch):
    db, _run = operations_db
    service = MCPOperationsService(db)
    monkeypatch.setattr(settings, "mcp_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "mcp_circuit_cooldown_seconds", 60)

    service.before_execution("tracker", "execution-1")
    first = service.record_transport_failure("tracker", TimeoutError("one"), 10)
    first_state = first.circuit_state
    service.before_execution("tracker", "execution-2")
    opened = service.record_transport_failure("tracker", TimeoutError("two"), 20)

    assert first_state == "closed"
    assert opened.circuit_state == "open"
    assert opened.circuit_open_count == 1
    with pytest.raises(MCPCircuitOpenError):
        service.before_execution("tracker", "execution-blocked")
    db.refresh(opened)
    assert opened.circuit_rejections == 1

    opened.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.add(opened)
    db.commit()
    half_open = service.before_execution("tracker", "execution-trial")
    half_open_state = half_open.circuit_state
    half_open_trial_id = half_open.half_open_trial_id
    closed = service.record_transport_success("tracker", 5)

    assert half_open_state == "half_open"
    assert half_open_trial_id == "execution-trial"
    assert closed.circuit_state == "closed"
    assert closed.consecutive_failures == 0


def test_manual_circuit_control_is_versioned_and_resettable(operations_db):
    db, _run = operations_db
    service = MCPOperationsService(db)
    health = service.register_servers(
        [{"name": "docs", "url": "https://mcp.example/docs"}]
    )[0]
    stale_version = health.version

    opened = service.control_circuit(
        "docs",
        action="open",
        expected_version=stale_version,
    )
    assert opened.manual_open is True
    assert opened.cooldown_until is None
    with pytest.raises(MCPCircuitConflictError, match="version conflict"):
        service.control_circuit("docs", action="close", expected_version=stale_version)

    reset = service.control_circuit(
        "docs",
        action="reset",
        expected_version=opened.version,
    )
    assert reset.circuit_state == "closed"
    assert reset.manual_open is False
    assert reset.circuit_open_count == 0


def test_health_probes_update_protocol_and_drive_health_state(operations_db, monkeypatch):
    db, _run = operations_db
    service = MCPOperationsService(db)
    monkeypatch.setattr(settings, "mcp_circuit_failure_threshold", 1)

    class FakeClient:
        def __init__(self):
            self.fail = False

        def configured_servers(self):
            return [{"name": "docs", "url": "https://mcp.example/docs"}]

        async def probe(self, _name):
            if self.fail:
                raise TimeoutError("probe timeout")
            return {
                "protocol_version": "2025-11-25",
                "server_info": {"name": "docs", "version": "1.0"},
            }

    client = FakeClient()
    healthy = service.probe_servers(client)[0]
    healthy_status = healthy.last_probe_status
    protocol_version = healthy.protocol_version
    client.fail = True
    unhealthy = service.probe_servers(client)[0]

    assert healthy_status == "healthy"
    assert protocol_version == "2025-11-25"
    assert unhealthy.last_probe_status == "unhealthy"
    assert unhealthy.circuit_state == "open"
    assert unhealthy.failed_probes == 1


def test_execution_service_obeys_manual_circuit_without_remote_call(operations_db):
    db, run = operations_db
    operations = MCPOperationsService(db)
    health = operations.register_servers(
        [{"name": "tracker", "url": "https://mcp.example/tracker"}]
    )[0]
    operations.control_circuit(
        "tracker",
        action="open",
        expected_version=health.version,
    )
    execution = MCPExecutionService(db).prepare(
        run_id=run.id,
        call={
            "qualified_name": "tracker.update",
            "server": "tracker",
            "tool": "update",
            "arguments": {"id": "1"},
        },
        idempotency_key=execution_idempotency_key("circuit-test"),
        idempotency_mode="metadata",
    )
    calls = []

    result = MCPExecutionService(db).execute_once(
        execution,
        lambda *_args: calls.append(True) or {"ok": True},
    )

    assert calls == []
    assert result["error"] == "mcp_circuit_open"
    assert MCPExecutionService(db).get(execution.id).status == "failed"


def test_snapshot_and_prometheus_include_execution_recovery_and_alerts(
    operations_db,
    monkeypatch,
):
    db, run = operations_db
    monkeypatch.setattr(settings, "mcp_alert_unknown_age_seconds", 1)
    service = MCPExecutionService(db)
    execution = service.prepare(
        run_id=run.id,
        call={
            "qualified_name": "docs.search",
            "server": "docs",
            "tool": "search",
            "arguments": {"query": "MCP"},
        },
        idempotency_key=execution_idempotency_key("metrics"),
        idempotency_mode="none",
    )
    claim = service.claim(execution.id)
    unknown = service.mark_unknown(
        execution.id,
        lease_token=claim.lease_token or "",
        reason="outcome unknown",
    )
    unknown.updated_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    unknown.recovery_count = 2
    db.add(unknown)
    db.commit()

    operations = MCPOperationsService(db)
    snapshot = operations.snapshot(window_minutes=60)
    metrics = operations.prometheus(window_minutes=60)

    assert snapshot["summary"]["unknown"] == 1
    assert snapshot["summary"]["recovery_count"] == 2
    assert snapshot["alerts"][0]["type"] == "unknown_execution_stale"
    assert 'codemate_mcp_executions{status="unknown"} 1' in metrics
    assert "codemate_mcp_circuit_state" in metrics
