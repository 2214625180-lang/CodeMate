from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import queue as queue_module
from app.core.config import settings
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.mcp_execution_service import (
    MCPExecutionConflictError,
    MCPExecutionReconciliationRequired,
    MCPExecutionService,
    execution_idempotency_key,
)
from app.services.mcp_quota_service import MCPQuotaExceededError


@pytest.fixture
def execution_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'executions.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-1",
        name="repo",
        repo_url="https://example.com/repo.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-1",
        repo_id=repository.id,
        user_input="update issue",
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


def call(arguments=None):
    return {
        "qualified_name": "tracker.update_issue",
        "server": "tracker",
        "tool": "update_issue",
        "arguments": arguments or {"issue_id": "ISSUE-1", "token": "hidden"},
    }


def test_success_is_deduplicated_and_public_payload_is_redacted(execution_db):
    db, run = execution_db
    service = MCPExecutionService(db)
    key = execution_idempotency_key("run", run.id, 0)
    execution = service.prepare(
        run_id=run.id,
        call=call(),
        idempotency_key=key,
        idempotency_mode="metadata",
    )
    invocations = []

    first = service.execute_once(
        execution,
        lambda idempotency_key, execution_id: invocations.append(
            (idempotency_key, execution_id)
        )
        or {"ok": True, "result": {"updated": True}},
    )
    second = service.execute_once(execution, lambda *_args: pytest.fail("duplicate call"))

    assert len(invocations) == 1
    assert first["execution_id"] == execution.id
    assert second["deduplicated"] is True
    assert service.get(execution.id).status == "succeeded"
    assert service.public_dict(execution)["arguments"]["token"] == "***redacted***"


def test_ambiguous_failure_requires_reconciliation_and_never_blindly_retries(execution_db):
    db, run = execution_db
    service = MCPExecutionService(db)
    execution = service.prepare(
        run_id=run.id,
        call=call(),
        idempotency_key=execution_idempotency_key("run", run.id, "unknown"),
        idempotency_mode="none",
        checkpoint={"run_id": run.id, "repo_id": run.repo_id, "resume_from": "mcp_call"},
    )

    with pytest.raises(MCPExecutionReconciliationRequired) as caught:
        service.execute_once(execution, lambda *_args: (_ for _ in ()).throw(TimeoutError()))

    unknown = caught.value.execution
    assert unknown.status == "unknown"
    assert service.verify_checkpoint(unknown) is True
    with pytest.raises(MCPExecutionConflictError, match="retry is unsafe"):
        service.reconcile(
            execution_id=unknown.id,
            action="retry",
            expected_version=unknown.version,
            actor="alice",
            provider="github",
            note=None,
            result=None,
        )

    reconciled = service.reconcile(
        execution_id=unknown.id,
        action="confirm_succeeded",
        expected_version=unknown.version,
        actor="alice",
        provider="github",
        note="Verified in tracker",
        result={"ok": True, "result": {"updated": True}},
    )
    cached = service.execute_once(reconciled, lambda *_args: pytest.fail("must use ledger"))
    assert cached["deduplicated"] is True
    assert reconciled.reconciled_by == "alice"


def test_expired_lease_retries_only_with_remote_idempotency_contract(
    execution_db,
    monkeypatch,
):
    db, run = execution_db
    service = MCPExecutionService(db)
    monkeypatch.setattr(settings, "mcp_execution_max_attempts", 3)
    safe = service.prepare(
        run_id=run.id,
        call=call({"issue_id": "SAFE"}),
        idempotency_key=execution_idempotency_key("safe"),
        idempotency_mode="metadata",
    )
    unsafe = service.prepare(
        run_id=run.id,
        call=call({"issue_id": "UNSAFE"}),
        idempotency_key=execution_idempotency_key("unsafe"),
        idempotency_mode="none",
    )
    for execution in (safe, unsafe):
        claimed = service.claim(execution.id).execution
        claimed.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.add(claimed)
        db.commit()

    recovered_safe = service.recover_stale(safe.id)
    recovered_unsafe = service.recover_stale(unsafe.id)

    assert recovered_safe is not None and recovered_safe.status == "prepared"
    assert recovered_safe.recovery_count == 1
    assert recovered_unsafe is not None and recovered_unsafe.status == "unknown"
    db.refresh(run)
    assert run.status == "waiting_reconciliation"


def test_idempotency_key_cannot_be_rebound_to_different_arguments(execution_db):
    db, run = execution_db
    service = MCPExecutionService(db)
    key = execution_idempotency_key("fixed")
    service.prepare(
        run_id=run.id,
        call=call({"issue_id": "ONE"}),
        idempotency_key=key,
        idempotency_mode="none",
    )

    with pytest.raises(MCPExecutionConflictError, match="different MCP request"):
        service.prepare(
            run_id=run.id,
            call=call({"issue_id": "TWO"}),
            idempotency_key=key,
            idempotency_mode="none",
        )


def test_quota_denial_is_a_known_failure_not_an_unknown_remote_outcome(execution_db):
    db, run = execution_db
    service = MCPExecutionService(db)
    execution = service.prepare(
        run_id=run.id,
        call=call(),
        idempotency_key=execution_idempotency_key("quota-denied"),
        idempotency_mode="metadata",
    )

    result = service.execute_once(
        execution,
        lambda *_args: (_ for _ in ()).throw(
            MCPQuotaExceededError(
                "run_call_limit",
                policy_id="policy-1",
                retry_after_seconds=None,
                detail="run quota exceeded",
            )
        ),
    )

    assert result["error"] == "mcp_quota_exceeded"
    assert result["reason"] == "run_call_limit"
    assert service.get(execution.id).status == "failed"
