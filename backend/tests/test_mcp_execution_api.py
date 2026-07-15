from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import mcp_executions
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.mcp_execution_service import MCPExecutionService, execution_idempotency_key


def create_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'execution-api.db'}")
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
        service = MCPExecutionService(db)
        execution = service.prepare(
            run_id=run.id,
            call={
                "qualified_name": "tracker.update",
                "server": "tracker",
                "tool": "update",
                "arguments": {"issue_id": "ISSUE-1"},
            },
            idempotency_key=execution_idempotency_key("api"),
            idempotency_mode="none",
            checkpoint={"run_id": run.id, "repo_id": run.repo_id},
        )
        claim = service.claim(execution.id)
        execution = service.mark_unknown(
            execution.id,
            lease_token=claim.lease_token or "",
            reason="worker lost",
        )
        execution_id = execution.id

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "evaluation_admin_token", "execution-admin-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    monkeypatch.setattr(
        mcp_executions,
        "enqueue_agent_execution_resume",
        lambda execution_id, version: f"job-{execution_id}-v{version}",
    )
    app = FastAPI()
    app.include_router(mcp_executions.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), execution_id


def test_execution_api_requires_admin_and_reconciles_unknown_result(tmp_path, monkeypatch):
    client, execution_id = create_client(tmp_path, monkeypatch)

    unauthorized = client.get("/mcp-executions/runs/run-1")
    headers = {"Authorization": "Bearer execution-admin-token"}
    listed = client.get("/mcp-executions/runs/run-1", headers=headers)
    execution = listed.json()[0]
    reconciled = client.post(
        f"/mcp-executions/{execution_id}/reconcile",
        headers=headers,
        json={
            "action": "confirm_succeeded",
            "expected_version": execution["version"],
            "note": "verified remotely",
            "result": {"ok": True, "result": {"updated": True}},
        },
    )

    assert unauthorized.status_code == 401
    assert listed.status_code == 200
    assert execution["status"] == "unknown"
    assert reconciled.status_code == 200
    assert reconciled.json()["execution"]["status"] == "succeeded"
    assert reconciled.json()["job_id"].startswith("job-")
