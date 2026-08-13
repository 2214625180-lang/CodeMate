import json
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import repos, runs
from app.api import auth as product_auth
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.services.agent_step_service import AgentStepService


def make_client(tmp_path, monkeypatch, *, owner_id: str = "local:local-dev"):
    engine = create_engine(f"sqlite:///{tmp_path / 'product-api.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    workspace = tmp_path / "repository"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "cart.py").write_text(
        "def total():\n    return 1\n", encoding="utf-8"
    )
    outside = tmp_path / "outside.py"
    outside.write_text("host_secret = True\n", encoding="utf-8")
    (workspace / "src" / "escape.py").symlink_to(outside)
    with session_factory() as db:
        repository = Repository(
            id="repo-product",
            name="product",
            owner_id=owner_id,
            repo_url="https://example.com/product.git",
            local_path=str(workspace),
            status="indexed",
        )
        code_file = CodeFile(
            id="file-product",
            repo_id=repository.id,
            file_path="src/cart.py",
            language="python",
            content_hash="cart-hash",
            line_count=2,
            size_bytes=25,
        )
        malicious_file = CodeFile(
            id="file-malicious",
            repo_id=repository.id,
            file_path="../outside.py",
            language="python",
            content_hash="outside-hash",
            line_count=1,
            size_bytes=1,
        )
        symlink_file = CodeFile(
            id="file-symlink",
            repo_id=repository.id,
            file_path="src/escape.py",
            language="python",
            content_hash="escape-hash",
            line_count=1,
            size_bytes=1,
        )
        run = AgentRun(
            id="run-product",
            repo_id=repository.id,
            owner_id=owner_id,
            user_input="Fix cart total",
            status="verified_success",
            final_diff="--- a/src/cart.py\n+++ b/src/cart.py\n@@\n-return 1\n+return 2\n",
            final_summary="Verified after targeted and regression tests.",
            test_result={"status": "verified_success"},
        )
        verification = AgentStep(
            id="step-verification",
            run_id=run.id,
            step_type="verification",
            output_json={"status": "verified_success"},
        )
        db.add_all([repository, code_file, malicious_file, symlink_file, run, verification])
        db.commit()

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    class StubChatService:
        def __init__(self, _db) -> None:
            pass

        def stream_chat(self, *, repo_id: str, question: str):
            yield f"event: token\ndata: {repo_id}:{question}\n\n"

    class StubReviewService:
        def __init__(self, _db) -> None:
            pass

        def review(self, *, repo_id: str, request):
            return {
                "summary": f"Reviewed {repo_id}",
                "changed_files": ["src/cart.py"],
                "findings": [],
                "citations": [],
            }

    class StubAgentService:
        def __init__(self, db) -> None:
            self.db = db

        def create_fix_run(self, *, repo_id: str, owner_id: str, issue: str, test_command, **_kwargs):
            run = AgentRun(
                id="run-created",
                repo_id=repo_id,
                owner_id=owner_id,
                user_input=issue,
                test_command=test_command,
                status="pending",
            )
            self.db.add(run)
            self.db.commit()
            return run

    queued_runs: list[str] = []
    monkeypatch.setattr(repos, "ChatService", StubChatService)
    monkeypatch.setattr(repos, "ReviewService", StubReviewService)
    monkeypatch.setattr(repos, "AgentService", StubAgentService)
    monkeypatch.setattr(repos, "enqueue_agent_run", queued_runs.append)
    monkeypatch.setattr(repos, "enqueue_repository_index", lambda *_args, **_kwargs: "queued")
    monkeypatch.setattr(runs, "SessionLocal", session_factory)

    app = FastAPI()
    app.include_router(repos.router)
    app.include_router(runs.router)
    app.dependency_overrides[get_db] = override_db
    app.state.timeline_session_factory = session_factory
    return TestClient(app), queued_runs


def product_headers(method: str, path: str, *, login: str, token: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    provider = "github"
    payload = product_auth.product_identity_signature_payload(
        method=method,
        path_with_query=path,
        timestamp=timestamp,
        nonce=nonce,
        login=login,
        provider=provider,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-CodeMate-Product-User": login,
        "X-CodeMate-Product-Provider": provider,
        "X-CodeMate-Product-Identity-Timestamp": timestamp,
        "X-CodeMate-Product-Identity-Nonce": nonce,
        "X-CodeMate-Product-Identity-Signature": product_auth.sign_identity_payload_with_secret(
            payload,
            token,
        ),
    }


def test_repository_chat_review_and_fix_api_cover_the_product_workflow(tmp_path, monkeypatch):
    client, queued_runs = make_client(tmp_path, monkeypatch)

    files = client.get("/repos/repo-product/files")
    content = client.get("/repos/repo-product/files/content?path=src/cart.py&start_line=2&end_line=2")
    traversal = client.get("/repos/repo-product/files/content?path=../outside.py")
    symlink_escape = client.get("/repos/repo-product/files/content?path=src/escape.py")
    chat = client.post("/repos/repo-product/chat", json={"question": "Where is the total?"})
    review = client.post(
        "/repos/repo-product/review",
        json={"diff": "--- a/src/cart.py\n+++ b/src/cart.py\n"},
    )
    fix = client.post(
        "/repos/repo-product/fix",
        json={"issue": "cart total is wrong", "test_command": "pytest"},
    )

    assert files.status_code == 200
    assert [item["file_path"] for item in files.json()] == [
        "../outside.py",
        "src/cart.py",
        "src/escape.py",
    ]
    assert content.json()["content"] == "    return 1"
    assert traversal.status_code == 400
    assert symlink_escape.status_code == 400
    assert "repo-product:Where is the total?" in chat.text
    assert review.json()["changed_files"] == ["src/cart.py"]
    assert fix.status_code == 202
    assert fix.json() == {"run_id": "run-created", "status": "pending"}
    assert queued_runs == ["run-created"]


def test_run_api_returns_timeline_and_persists_user_feedback(tmp_path, monkeypatch):
    client, _queued_runs = make_client(tmp_path, monkeypatch)

    run = client.get("/runs/run-product")
    trace = client.get("/runs/run-product/trace")
    feedback = client.post(
        "/runs/run-product/feedback",
        json={"status": "accepted", "note": "matches the expected diff"},
    )

    assert run.status_code == 200
    assert run.json()["steps"][0]["step_type"] == "verification"
    assert "event: verification" in trace.text
    assert feedback.json() == {
        "run_id": "run-product",
        "feedback_status": "accepted",
        "feedback_note": "matches the expected diff",
    }
    assert client.get("/runs/missing").status_code == 404


def test_restricted_timeline_requires_admin_and_public_timeline_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mcp_registry_kms_provider", "local")
    monkeypatch.setattr(settings, "mcp_registry_master_key", "product-timeline-key-32-characters-long")
    monkeypatch.setattr(settings, "mcp_registry_previous_master_key", None)
    monkeypatch.setattr(settings, "evaluation_admin_token", "timeline-admin-token")
    client, _queued_runs = make_client(tmp_path, monkeypatch)
    with client.app.state.timeline_session_factory() as db:
        AgentStepService(db).record(
            run_id="run-product",
            step_type="tool_result",
            output_json={"stderr": "API_TOKEN=product-timeline-secret", "exit_code": 1},
        )

    public = client.get("/runs/run-product")
    denied = client.get("/runs/run-product/timeline/restricted")
    admin = client.get(
        "/runs/run-product/timeline/restricted",
        headers={"Authorization": "Bearer timeline-admin-token"},
    )

    assert public.status_code == 200
    assert "product-timeline-secret" not in json.dumps(public.json())
    assert denied.status_code == 401
    assert admin.status_code == 200
    assert admin.json()[-1]["output_json"]["stderr"] == "API_TOKEN=product-timeline-secret"


def test_product_api_requires_signed_identity_and_scopes_resources_to_owner(tmp_path, monkeypatch):
    token = "p" * 32
    monkeypatch.setattr(product_auth.settings, "product_api_token", token)
    monkeypatch.setattr(product_auth.settings, "codemate_product_identity_secret", None)
    client, _queued_runs = make_client(tmp_path, monkeypatch, owner_id="github:alice")

    assert client.get("/repos").status_code == 401

    alice_headers = product_headers("GET", "/repos", login="alice", token=token)
    alice_repositories = client.get("/repos", headers=alice_headers)
    assert [item["id"] for item in alice_repositories.json()] == ["repo-product"]

    bob_headers = product_headers("GET", "/repos", login="bob", token=token)
    assert client.get("/repos", headers=bob_headers).json() == []
    assert client.get(
        "/repos/repo-product",
        headers=product_headers("GET", "/repos/repo-product", login="bob", token=token),
    ).status_code == 404

    fix = client.post(
        "/repos/repo-product/fix",
        headers=product_headers("POST", "/repos/repo-product/fix", login="alice", token=token),
        json={"issue": "cart total is wrong", "test_command": "pytest"},
    )
    assert fix.status_code == 202
    assert client.get(
        "/runs/run-created",
        headers=product_headers("GET", "/runs/run-created", login="bob", token=token),
    ).status_code == 404
