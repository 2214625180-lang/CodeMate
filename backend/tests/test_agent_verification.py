from types import SimpleNamespace

from app.agent.graph import build_fix_graph
from app.agent.verification import (
    build_verification_result,
    route_after_regression_checks,
    route_after_reproduction,
    route_after_targeted_tests,
    verification_evidence_is_complete,
)
from app.schemas.evaluations import FixEvaluationCase
from app.core.config import settings
from app.sandbox.runner import SandboxService, TestResult as SandboxTestResult
from app.services.evaluation_service import EvaluationService


def test_test_result_never_passes_without_execution_evidence():
    result = SandboxTestResult(
        passed=True,
        exit_code=0,
        stdout="",
        stderr="",
        command=None,
        tests_ran=False,
    )

    assert result.passed is False
    assert result.failure_kind == "infrastructure"


def test_missing_command_is_a_skipped_test_not_a_pass(tmp_path):
    result = SandboxService().run_tests(workspace=tmp_path, command=None)

    assert result.passed is False
    assert result.tests_ran is False
    assert result.failure_kind == "skipped"
    assert result.skipped_reason


def test_offline_dependency_skip_is_not_a_pass(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.32.4\n", encoding="utf-8")
    monkeypatch.setattr(settings, "sandbox_runtime", "docker")
    monkeypatch.setattr(settings, "sandbox_network_disabled", True)

    result = SandboxService().run_tests(workspace=tmp_path, command="pytest")

    assert result.passed is False
    assert result.tests_ran is False
    assert result.failure_kind == "skipped"
    assert "network" in (result.skipped_reason or "").lower()


def test_dependency_failure_before_test_start_is_infrastructure_error():
    sandbox = SandboxService()
    shell_command = sandbox._test_shell_command(
        dependency_command="python -m pip install -r requirements.txt",
        command="pytest",
    )
    dependency_failure = sandbox.test_result_from_execution(
        reported_passed=False,
        exit_code=125,
        stdout="pip install failed",
        stderr="network unavailable",
        command="pytest",
        runtime="docker",
    )
    assertion_failure = sandbox.test_result_from_execution(
        reported_passed=False,
        exit_code=1,
        stdout="1 failed",
        stderr="assertion failed",
        command="pytest",
        runtime="docker",
    )

    assert dependency_failure.tests_ran is False
    assert dependency_failure.failure_kind == "infrastructure"
    assert "|| exit 125; pytest" in shell_command
    assert assertion_failure.tests_ran is True
    assert assertion_failure.failure_kind == "test_failure"


def test_verified_success_requires_reproduction_and_both_post_patch_suites():
    result = build_verification_result(
        {
            "baseline_test_result": failed_test("baseline"),
            "apply_result": {"ok": True},
            "targeted_test_result": passed_test("targeted"),
            "regression_test_result": passed_test("regression"),
        }
    )

    assert result["status"] == "verified_success"
    assert result["tests_ran"] is True
    assert verification_evidence_is_complete(result) is True
    assert verification_evidence_is_complete(
        {"status": "verified_success", "passed": True, "tests_ran": True, "exit_code": 0}
    ) is False


def test_verification_terminal_statuses_preserve_uncertainty():
    not_reproduced = build_verification_result(
        {"baseline_test_result": passed_test("baseline")}
    )
    unverified = build_verification_result(
        {
            "baseline_test_result": skipped_test("baseline"),
            "apply_result": {"ok": True},
            "targeted_test_result": skipped_test("targeted"),
        }
    )
    failed = build_verification_result(
        {
            "baseline_test_result": failed_test("baseline"),
            "apply_result": {"ok": False},
        }
    )
    infra_error = build_verification_result(
        {"baseline_test_result": infrastructure_error("baseline")}
    )

    assert not_reproduced["status"] == "not_reproduced"
    assert unverified["status"] == "unverified_patch"
    assert failed["status"] == "failed"
    assert infra_error["status"] == "infra_error"
    assert not any(
        result["passed"] for result in (not_reproduced, unverified, failed, infra_error)
    )


def test_graph_routes_baseline_and_post_patch_results_by_evidence():
    assert route_after_reproduction({"baseline_test_result": passed_test("baseline")}) == "final"
    assert route_after_reproduction({"baseline_test_result": failed_test("baseline")}) == "continue"
    assert (
        route_after_targeted_tests(
            {
                "apply_result": {"ok": True},
                "targeted_test_result": passed_test("targeted"),
                "iterations": 1,
                "max_iterations": 3,
            }
        )
        == "regression"
    )
    assert (
        route_after_regression_checks(
            {
                "regression_test_result": failed_test("regression"),
                "iterations": 3,
                "max_iterations": 3,
            }
        )
        == "final"
    )


def test_fix_graph_runs_reproduction_before_patch_and_regression_checks():
    visited: list[str] = []

    def node(name: str, output: dict | None = None):
        def invoke(_state: dict) -> dict:
            visited.append(name)
            return output or {}

        return invoke

    graph = build_fix_graph(
        {
            "inspect_repository": node("inspect"),
            "reproduce_failure": node(
                "reproduce",
                {"baseline_test_result": failed_test("baseline")},
            ),
            "initialize_agent_loop": node("initialize"),
            "plan_next_action": node(
                "plan",
                {"current_action": {"action": "GeneratePatch"}},
            ),
            "execute_local_action": node(
                "execute",
                {"action_outcome": {"route": "generate"}},
            ),
            "plan_mcp_tools": node("plan_mcp", {"mcp_tool_plan": {"calls": []}}),
            "call_mcp_tools": node("call_mcp"),
            "observe_mcp": node("observe_mcp"),
            "pause_for_approval": node("pause_approval"),
            "pause_for_reconciliation": node("pause_reconciliation"),
            "generate_patch": node("generate", {"patch": "diff"}),
            "apply_patch": node("apply", {"apply_result": {"ok": True}}),
            "targeted_tests": node(
                "targeted",
                {
                    "targeted_test_result": passed_test("targeted"),
                    "iterations": 1,
                },
            ),
            "regression_checks": node(
                "regression",
                {"regression_test_result": passed_test("regression")},
            ),
            "reflect": node("reflect"),
            "final_answer": node("final", {"status": "verified_success"}),
        }
    )

    final_state = graph.invoke({"iterations": 0, "max_iterations": 3})

    assert final_state["status"] == "verified_success"
    assert visited == [
        "inspect",
        "reproduce",
        "initialize",
        "plan",
        "execute",
        "plan_mcp",
        "generate",
        "apply",
        "targeted",
        "regression",
        "final",
    ]


def test_fix_evaluation_legacy_success_normalizes_to_verified_success():
    case = FixEvaluationCase(
        repo_id="repo-id",
        issue="failure",
        expected_status="success",  # type: ignore[arg-type] - legacy API input.
    )

    assert case.expected_status == "verified_success"


def test_fix_success_rate_counts_only_verified_success():
    results = [
        SimpleNamespace(passed=True, result_json={"agent_status": "verified_success"}),
        SimpleNamespace(passed=True, result_json={"agent_status": "not_reproduced"}),
        SimpleNamespace(passed=False, result_json={"agent_status": "unverified_patch"}),
    ]
    for result in results:
        result.latency_ms = None
        result.failure_category = None if result.passed else "tests_not_run"

    metrics = EvaluationService(None)._fix_metrics(results)  # type: ignore[arg-type]

    assert metrics["passed"] == 2
    assert metrics["verified_successes"] == 1
    assert metrics["fix_success_rate"] == 1 / 3


def passed_test(phase: str) -> dict:
    return {
        "passed": True,
        "exit_code": 0,
        "stdout": "passed",
        "stderr": "",
        "command": "pytest",
        "tests_ran": True,
        "timed_out": False,
        "failure_kind": None,
        "phase": phase,
    }


def failed_test(phase: str) -> dict:
    return {
        **passed_test(phase),
        "passed": False,
        "exit_code": 1,
        "stderr": "assertion failed",
        "failure_kind": "test_failure",
    }


def skipped_test(phase: str) -> dict:
    return {
        **passed_test(phase),
        "passed": False,
        "exit_code": 0,
        "tests_ran": False,
        "skipped_reason": "dependencies unavailable",
        "failure_kind": "skipped",
    }


def infrastructure_error(phase: str) -> dict:
    return {
        **passed_test(phase),
        "passed": False,
        "exit_code": 126,
        "tests_ran": False,
        "failure_kind": "infrastructure",
    }
