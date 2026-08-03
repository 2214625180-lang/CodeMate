from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core import queue as queue_module
from app.agent.graph import after_mcp_plan
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.agent_service import AgentService
from app.services.agent_step_service import AgentStepService
from app.services.mcp_approval_service import (
    MCPApprovalConflictError,
    MCPApprovalService,
)


@pytest.fixture
def approval_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'approvals.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    repository = Repository(
        id="repo-1",
        name="repo",
        repo_url="https://example.com/repo.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-1",
        repo_id=repository.id,
        user_input="Update external issue",
        status="running",
    )
    db.add_all([repository, run])
    db.commit()
    yield db, run
    db.close()


def create_approval(db, run):
    return MCPApprovalService(db).create_pending(
        run=run,
        call={
            "qualified_name": "tracker.update_issue",
            "server": "tracker",
            "tool": "update_issue",
            "arguments": {
                "issue_id": "ISSUE-1",
                "status": "done",
                "api_token": "must-not-leak",
            },
        },
        catalog_entry={
            "qualified_name": "tracker.update_issue",
            "server": "tracker",
            "name": "update_issue",
            "policy": "approval_required",
            "input_schema": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string"},
                    "status": {"type": "string"},
                    "api_token": {"type": "string"},
                },
                "required": ["issue_id", "status", "api_token"],
            },
        },
        checkpoint={
            "run_id": run.id,
            "repo_id": run.repo_id,
            "user_input": run.user_input,
            "diagnosis": "checkpoint",
            "mcp_router_round": 0,
            "mcp_call_count": 0,
            "mcp_max_rounds": 2,
            "mcp_max_calls": 4,
        },
    )


def test_create_approval_pauses_run_hashes_state_and_redacts_public_arguments(approval_db):
    db, run = approval_db

    approval = create_approval(db, run)
    public = MCPApprovalService.public_dict(approval)

    assert run.status == "waiting_approval"
    assert approval.status == "pending"
    assert len(approval.arguments_hash) == 64
    assert len(approval.checkpoint_hash) == 64
    assert approval.checkpoint_json["resume_from"] == "mcp_observe"
    assert approval.checkpoint_json["mcp_pending_approval_id"] == approval.id
    assert MCPApprovalService.verify_checkpoint(approval) is True
    assert public["arguments"]["api_token"] == "***redacted***"


def test_decision_is_versioned_idempotent_and_rejects_conflicting_replay(approval_db):
    db, run = approval_db
    service = MCPApprovalService(db)
    approval = create_approval(db, run)

    decided = service.decide(
        approval_id=approval.id,
        decision="approve",
        note="Looks safe",
        actor="alice",
        provider="github",
        expected_version=1,
    )
    replay = service.decide(
        approval_id=approval.id,
        decision="approve",
        note="Looks safe",
        actor="alice",
        provider="github",
        expected_version=1,
    )

    assert decided.status == "queued"
    assert decided.decision == "approved"
    assert decided.version == 2
    assert replay.id == decided.id
    with pytest.raises(MCPApprovalConflictError, match="version conflict"):
        service.decide(
            approval_id=approval.id,
            decision="reject",
            note=None,
            actor="bob",
            provider="github",
            expected_version=1,
        )


def test_expired_approval_is_rejected_and_checkpoint_tampering_is_detected(approval_db):
    db, run = approval_db
    service = MCPApprovalService(db)
    approval = create_approval(db, run)
    approval.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.add(approval)
    db.commit()

    expired = service.expire(approval.id)

    assert expired is not None
    assert expired.status == "queued"
    assert expired.decision == "rejected"
    expired.checkpoint_json["repo_id"] = "tampered"
    assert service.verify_checkpoint(expired) is False


def test_resume_executes_approved_tool_then_continues_from_checkpoint(approval_db, monkeypatch):
    db, run = approval_db
    approvals = MCPApprovalService(db)
    approval = create_approval(db, run)
    approval = approvals.decide(
        approval_id=approval.id,
        decision="approve",
        note=None,
        actor="alice",
        provider="github",
        expected_version=1,
    )
    executed = []

    class FakeRouter:
        def discover_catalog(self):
            return {"tools": [approval.catalog_entry_json], "errors": []}

        def execute_approved(self, **kwargs):
            executed.append(kwargs)
            return {
                "ok": True,
                "qualified_name": approval.qualified_name,
                "arguments": approval.arguments_json,
                "result": {"structuredContent": {"updated": True}},
            }

    agent = AgentService(db)
    monkeypatch.setattr(agent, "_create_mcp_router", lambda _run=None: FakeRouter())
    monkeypatch.setattr(
        agent,
        "_invoke_fix_graph",
        lambda _run, state: {
            **state,
            "status": "verified_success",
            "final_summary": "resumed",
            "final_diff": "",
            "verification_result": {
                "status": "verified_success",
                "passed": True,
                "tests_ran": True,
                "patch_applied": True,
                "baseline": {
                    "passed": False,
                    "tests_ran": True,
                    "exit_code": 1,
                    "failure_kind": "test_failure",
                },
                "targeted": {
                    "passed": True,
                    "tests_ran": True,
                    "exit_code": 0,
                },
                "regression": {
                    "passed": True,
                    "tests_ran": True,
                    "exit_code": 0,
                },
            },
            "iterations": 0,
        },
    )

    agent.resume_from_approval(approval.id)

    db.refresh(approval)
    db.refresh(run)
    assert approval.status == "completed"
    assert run.status == "verified_success"
    assert executed[0]["expected_arguments_hash"] == approval.arguments_hash
    assert any(step.tool_name == "tracker.update_issue" for step in run.steps)


def test_agent_plan_persists_checkpoint_and_routes_to_pause(approval_db, monkeypatch):
    db, run = approval_db
    catalog_entry = {
        "qualified_name": "tracker.update_issue",
        "server": "tracker",
        "name": "update_issue",
        "policy": "approval_required",
        "input_schema": {
            "type": "object",
            "properties": {"issue_id": {"type": "string"}},
            "required": ["issue_id"],
        },
    }

    class ApprovalRouter:
        def discover_catalog(self):
            return {"tools": [catalog_entry], "errors": []}

        def plan(self, **_kwargs):
            return {
                "calls": [],
                "approval_requests": [
                    {
                        "qualified_name": "tracker.update_issue",
                        "server": "tracker",
                        "tool": "update_issue",
                        "arguments": {"issue_id": "ISSUE-1"},
                    }
                ],
                "rejected": [],
            }

    monkeypatch.setattr(
        queue_module,
        "enqueue_approval_expiration",
        lambda approval_id, delay_seconds: f"expiry-{approval_id}-{delay_seconds}",
    )
    agent = AgentService(db)
    monkeypatch.setattr(agent, "_create_mcp_router", lambda _run=None: ApprovalRouter())
    nodes = agent._nodes(run, object(), AgentStepService(db))
    state = {
        **agent._initial_state(run),
        "diagnosis": "local",
        "files": {"main.py": "pass"},
    }

    planned = nodes["plan_mcp_tools"](state)

    assert planned["mcp_pending_approval_id"]
    assert after_mcp_plan(planned) == "pause"
    approval = MCPApprovalService(db).get(planned["mcp_pending_approval_id"])
    assert approval.checkpoint_json["files"] == {"main.py": "pass"}
    assert run.status == "waiting_approval"
