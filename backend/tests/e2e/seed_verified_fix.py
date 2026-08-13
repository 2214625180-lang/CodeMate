"""Seed a deterministic completed run for the browser-to-API E2E contract."""

from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.repository import Repository


REPOSITORY_ID = "e2e-demo-cart"
RUN_ID = "e2e-run-demo-cart"

FINAL_DIFF = """--- a/src/checkout.js
+++ b/src/checkout.js
@@
-  const tax = calculateTax(subtotal, taxRate);
+  const tax = calculateTax(discountedSubtotal, taxRate);
"""

BASELINE = {
    "command": "npm test",
    "tests_ran": True,
    "exit_code": 1,
    "passed": False,
    "stdout": "not ok 1 - calculates tax after the coupon discount",
    "stderr": "Expected 108, received 110",
}
TARGETED = {
    "command": "npm run test:targeted",
    "tests_ran": True,
    "exit_code": 0,
    "passed": True,
    "stdout": "ok 1 - calculates tax after the coupon discount",
    "stderr": "",
}
REGRESSION = {
    "command": "npm test",
    "tests_ran": True,
    "exit_code": 0,
    "passed": True,
    "stdout": "ok 1 - coupon checkout\nok 2 - checkout tax regression",
    "stderr": "",
}


def main() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        existing_run = db.get(AgentRun, RUN_ID)
        if existing_run is not None:
            db.delete(existing_run)
            db.flush()
        existing_repository = db.get(Repository, REPOSITORY_ID)
        if existing_repository is not None:
            db.delete(existing_repository)
            db.flush()

        repository = Repository(
            id=REPOSITORY_ID,
            name="e2e-demo-cart-bug",
            repo_url="https://example.test/e2e-demo-cart-bug.git",
            local_path="/fixtures/e2e-demo-cart-bug",
            status="indexed",
            language_summary={"javascript": 3},
            last_commit_hash="e2e-fixture-commit",
            file_count=3,
            chunk_count=6,
            indexed_at=now,
            created_at=now,
            updated_at=now,
        )
        run = AgentRun(
            id=RUN_ID,
            repo_id=REPOSITORY_ID,
            task_type="fix",
            principal_type="agent",
            principal_id="codemate-agent",
            user_input="Coupon tax is calculated before the discount, so checkout total is too high.",
            test_command="npm test",
            status="verified_success",
            final_diff=FINAL_DIFF,
            final_summary="Baseline failure reproduced; targeted and regression tests passed.",
            test_result={
                "status": "verified_success",
                "baseline": BASELINE,
                "targeted": TARGETED,
                "regression": REGRESSION,
            },
            iterations=2,
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
        db.add_all(
            [
                repository,
                run,
                AgentStep(
                    id="e2e-step-plan",
                    run_id=RUN_ID,
                    step_type="agent_plan",
                    tool_name="plan_next_action",
                    output_json={"action": {"action": "SearchCode"}},
                    created_at=now,
                ),
                AgentStep(
                    id="e2e-step-patch",
                    run_id=RUN_ID,
                    step_type="patch",
                    output_json={"diff": FINAL_DIFF},
                    created_at=now,
                ),
                AgentStep(
                    id="e2e-step-verification",
                    run_id=RUN_ID,
                    step_type="verification",
                    output_json={
                        "status": "verified_success",
                        "baseline": BASELINE,
                        "targeted": TARGETED,
                        "regression": REGRESSION,
                    },
                    created_at=now,
                ),
                AgentStep(
                    id="e2e-step-final",
                    run_id=RUN_ID,
                    step_type="final",
                    output_json={"status": "verified_success"},
                    created_at=now,
                ),
            ]
        )
        db.commit()


if __name__ == "__main__":
    main()
