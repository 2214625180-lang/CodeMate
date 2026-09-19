"""Seed deterministic Alice/Bob fixtures for the protected product E2E suite."""

from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository


BASELINE = {
    "command": "npm test",
    "tests_ran": True,
    "exit_code": 1,
    "passed": False,
    "stdout": "not ok 1 - protected fixture reproduces the failure",
    "stderr": "Expected the protected fixture to fail before the patch",
}
TARGETED = {
    "command": "npm run test:targeted",
    "tests_ran": True,
    "exit_code": 0,
    "passed": True,
    "stdout": "ok 1 - protected targeted test",
    "stderr": "",
}
REGRESSION = {
    "command": "npm test",
    "tests_ran": True,
    "exit_code": 0,
    "passed": True,
    "stdout": "ok 1 - protected targeted test\nok 2 - protected regression test",
    "stderr": "",
}

FIXTURES = (
    {
        "login": "alice",
        "repo_id": "e2e-alice-repo",
        "repo_name": "alice-protected-cart",
        "run_id": "e2e-alice-run",
        "file_path": "src/checkout.js",
        "symbol_name": "calculateTotal",
        "content": (
            "export function calculateTotal(subtotal, discount, taxRate) {\n"
            "  const discountedSubtotal = subtotal - discount;\n"
            "  return discountedSubtotal + discountedSubtotal * taxRate;\n"
            "}\n"
        ),
        "diff": (
            "diff --git a/src/checkout.js b/src/checkout.js\n"
            "--- a/src/checkout.js\n"
            "+++ b/src/checkout.js\n"
            "@@\n"
            "-  return subtotal + subtotal * taxRate;\n"
            "+  return discountedSubtotal + discountedSubtotal * taxRate;\n"
        ),
    },
    {
        "login": "bob",
        "repo_id": "e2e-bob-repo",
        "repo_name": "bob-protected-inventory",
        "run_id": "e2e-bob-run",
        "file_path": "src/inventory.js",
        "symbol_name": "reserveInventory",
        "content": (
            "export function reserveInventory(available, requested) {\n"
            "  return available >= requested;\n"
            "}\n"
        ),
        "diff": (
            "diff --git a/src/inventory.js b/src/inventory.js\n"
            "--- a/src/inventory.js\n"
            "+++ b/src/inventory.js\n"
            "@@\n"
            "-  return available > requested;\n"
            "+  return available >= requested;\n"
        ),
    },
)


def main() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for fixture in FIXTURES:
            existing_run = db.get(AgentRun, fixture["run_id"])
            if existing_run is not None:
                db.delete(existing_run)
                db.flush()
            existing_repository = db.get(Repository, fixture["repo_id"])
            if existing_repository is not None:
                db.delete(existing_repository)
                db.flush()

        for fixture in FIXTURES:
            _seed_fixture(db, fixture=fixture, now=now)
        db.commit()


def _seed_fixture(db, *, fixture: dict[str, str], now: datetime) -> None:
    login = fixture["login"]
    repo_id = fixture["repo_id"]
    run_id = fixture["run_id"]
    file_id = f"{login}-protected-file"
    chunk_id = f"{login}-protected-chunk"
    owner_id = f"github:{login}"
    verification = {
        "status": "verified_success",
        "baseline": BASELINE,
        "targeted": TARGETED,
        "regression": REGRESSION,
    }

    repository = Repository(
        id=repo_id,
        name=fixture["repo_name"],
        owner_id=owner_id,
        repo_url=f"https://example.test/{fixture['repo_name']}.git",
        local_path=f"/fixtures/protected/{login}",
        status="indexed",
        language_summary={"javascript": 1},
        last_commit_hash=f"protected-{login}-fixture",
        file_count=1,
        chunk_count=1,
        indexed_at=now,
        created_at=now,
        updated_at=now,
    )
    code_file = CodeFile(
        id=file_id,
        repo_id=repo_id,
        file_path=fixture["file_path"],
        language="javascript",
        content_hash=f"{login}-protected-content",
        line_count=4,
        size_bytes=len(fixture["content"].encode("utf-8")),
        created_at=now,
        updated_at=now,
    )
    chunk = CodeChunk(
        id=chunk_id,
        repo_id=repo_id,
        file_id=file_id,
        file_path=fixture["file_path"],
        language="javascript",
        symbol_name=fixture["symbol_name"],
        symbol_type="function",
        start_line=1,
        end_line=4,
        content=fixture["content"],
        summary=f"Protected {login} fixture",
        content_hash=f"{login}-protected-chunk-content",
        created_at=now,
        updated_at=now,
    )
    run = AgentRun(
        id=run_id,
        repo_id=repo_id,
        owner_id=owner_id,
        task_type="fix",
        principal_type="agent",
        principal_id="codemate-agent",
        user_input=f"Fix the {login} protected fixture.",
        test_command="npm test",
        status="verified_success",
        final_diff=fixture["diff"],
        final_summary="Protected fixture reproduced and verified.",
        test_result=verification,
        iterations=1,
        created_at=now,
        updated_at=now,
        finished_at=now,
    )
    steps = [
        AgentStep(
            id=f"{login}-protected-plan",
            run_id=run_id,
            step_type="agent_plan",
            tool_name="plan_next_action",
            output_json={"action": {"action": "SearchCode"}},
            created_at=now,
        ),
        AgentStep(
            id=f"{login}-protected-verification",
            run_id=run_id,
            step_type="verification",
            output_json=verification,
            created_at=now + timedelta(milliseconds=1),
        ),
        AgentStep(
            id=f"{login}-protected-final",
            run_id=run_id,
            step_type="final",
            output_json={"status": "verified_success"},
            created_at=now + timedelta(milliseconds=2),
        ),
    ]
    db.add_all([repository, code_file, chunk, run, *steps])


if __name__ == "__main__":
    main()
