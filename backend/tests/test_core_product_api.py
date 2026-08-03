from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import repos, runs
from app.core.database import Base, get_db
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.code_file import CodeFile
from app.models.repository import Repository


def make_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'product-api.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    workspace = tmp_path / "repository"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "cart.py").write_text(
        "def total():\n    return 1\n", encoding="utf-8"
    )
    with session_factory() as db:
        repository = Repository(
            id="repo-product",
            name="product",
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
        run = AgentRun(
            id="run-product",
            repo_id=repository.id,
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
        db.add_all([repository, code_file, malicious_file, run, verification])
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

        def create_fix_run(self, *, repo_id: str, issue: str, test_command, **_kwargs):
            run = AgentRun(
                id="run-created",
                repo_id=repo_id,
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
    return TestClient(app), queued_runs


def test_repository_chat_review_and_fix_api_cover_the_product_workflow(tmp_path, monkeypatch):
    client, queued_runs = make_client(tmp_path, monkeypatch)

    files = client.get("/repos/repo-product/files")
    content = client.get("/repos/repo-product/files/content?path=src/cart.py&start_line=2&end_line=2")
    traversal = client.get("/repos/repo-product/files/content?path=../outside.py")
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
    assert [item["file_path"] for item in files.json()] == ["../outside.py", "src/cart.py"]
    assert content.json()["content"] == "    return 1"
    assert traversal.status_code == 400
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
