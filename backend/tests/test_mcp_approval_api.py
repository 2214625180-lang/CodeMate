from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import mcp_approvals
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.mcp_approval_service import MCPApprovalService


def create_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'approval-api.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        repository = Repository(
            id="repo-1",
            name="repo",
            repo_url="https://example.com/repo.git",
            status="indexed",
        )
        run = AgentRun(
            id="run-1",
            repo_id=repository.id,
            user_input="issue",
            status="running",
        )
        db.add_all([repository, run])
        db.commit()
        approval = MCPApprovalService(db).create_pending(
            run=run,
            call={
                "qualified_name": "docs.write",
                "server": "docs",
                "tool": "write",
                "arguments": {"text": "hello"},
            },
            catalog_entry={
                "qualified_name": "docs.write",
                "server": "docs",
                "name": "write",
                "policy": "approval_required",
                "input_schema": {"type": "object"},
            },
            checkpoint={"run_id": run.id, "repo_id": run.repo_id},
        )
        approval_id = approval.id

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "evaluation_admin_token", "approval-admin-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    monkeypatch.setattr(
        mcp_approvals,
        "enqueue_agent_approval_resume",
        lambda approval_id, version: f"job-{approval_id}-v{version}",
    )
    app = FastAPI()
    app.include_router(mcp_approvals.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), approval_id


def test_approval_api_requires_admin_token(tmp_path, monkeypatch):
    client, _approval_id = create_client(tmp_path, monkeypatch)

    response = client.get("/mcp-approvals/runs/run-1")

    assert response.status_code == 401


def test_admin_can_list_and_approve_pending_tool(tmp_path, monkeypatch):
    client, approval_id = create_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer approval-admin-token"}

    listed = client.get("/mcp-approvals/runs/run-1", headers=headers)
    decided = client.post(
        f"/mcp-approvals/{approval_id}/decision",
        headers=headers,
        json={"decision": "approve", "expected_version": 1, "note": "safe"},
    )

    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "pending"
    assert decided.status_code == 200
    assert decided.json()["decision"] == "approved"
    assert decided.json()["status"] == "queued"
    assert decided.json()["version"] == 2


def test_stale_conflicting_decision_is_rejected(tmp_path, monkeypatch):
    client, approval_id = create_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer approval-admin-token"}
    client.post(
        f"/mcp-approvals/{approval_id}/decision",
        headers=headers,
        json={"decision": "approve", "expected_version": 1},
    )

    conflict = client.post(
        f"/mcp-approvals/{approval_id}/decision",
        headers=headers,
        json={"decision": "reject", "expected_version": 1},
    )

    assert conflict.status_code == 409
    assert "version conflict" in conflict.json()["detail"]

