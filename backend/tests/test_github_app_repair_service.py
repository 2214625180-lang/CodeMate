from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.verification import VERIFIED_SUCCESS
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.github_app_repair_service import GitHubAppRepairService


class FakeGitHubAppClient:
    def __init__(self) -> None:
        self.draft_request: dict | None = None

    def read_failed_workflow_run(self, **_kwargs) -> dict:
        return {
            "repository_full_name": "octo/example",
            "workflow_run_id": "456",
            "workflow_url": "https://github.com/octo/example/actions/runs/456",
            "head_sha": "a" * 40,
            "base_branch": "main",
            "failure_summary": {
                "workflow_name": "test",
                "conclusion": "failure",
                "failed_jobs": [{"name": "pytest", "failed_steps": ["run tests"]}],
            },
        }

    def create_draft_pull_request(self, **kwargs) -> dict:
        self.draft_request = kwargs
        return {"number": 12, "html_url": "https://github.com/octo/example/pull/12"}


def test_failed_ci_repair_requires_verified_fix_and_human_approval(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'github-app.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-github",
        name="example",
        owner_id="github:octo",
        repo_url="https://github.com/octo/example.git",
        local_path=str(tmp_path),
        status="indexed",
    )
    db.add(repository)
    db.commit()
    client = FakeGitHubAppClient()
    service = GitHubAppRepairService(db, client=client)  # type: ignore[arg-type]

    repair = service.start_failed_ci_repair(
        repository=repository,
        installation_id="123",
        workflow_run_id="456",
    )
    run = db.get(AgentRun, repair.run_id)
    assert run is not None
    assert run.status == "pending"
    assert "GitHub Actions workflow failed" in run.user_input

    run.status = VERIFIED_SUCCESS
    run.final_diff = "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n"
    db.add(run)
    db.commit()
    assert service.sync_agent_result(run.id).status == "waiting_approval"  # type: ignore[union-attr]

    monkeypatch.setattr(service, "_push_verified_patch", lambda **_kwargs: None)
    decided = service.decide_draft_pr(
        repair=repair,
        approver="github:octo",
        approved=True,
        note="Reviewed the verified patch",
    )

    assert decided.status == "draft_pr_created"
    assert decided.pull_request_number == 12
    assert client.draft_request == {
        "installation_id": "123",
        "owner": "octo",
        "repository": "example",
        "branch_name": f"codemate/ci-fix/{repair.id[:12]}",
        "base_branch": "main",
        "title": "fix(ci): repair failed workflow run 456",
        "body": service._draft_pr_body(repair),
    }


def test_github_app_repair_parses_https_and_ssh_github_urls() -> None:
    assert GitHubAppRepairService._github_repository_name(
        "https://github.com/octo/example.git"
    ) == ("octo", "example")
    assert GitHubAppRepairService._github_repository_name(
        "git@github.com:octo/example.git"
    ) == ("octo", "example")
