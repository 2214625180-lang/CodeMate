from types import SimpleNamespace

import pytest

from app.services.evaluation_service import EvaluationService


def test_retrieval_case_requires_expected_line_overlap() -> None:
    service = EvaluationService(None)  # type: ignore[arg-type]
    citations = [
        {
            "file_path": "src/orders.py",
            "start_line": 1,
            "end_line": 20,
        },
        {
            "file_path": "src/orders.py",
            "start_line": 48,
            "end_line": 70,
        },
        {
            "file_path": "src/other.py",
            "start_line": 50,
            "end_line": 60,
        },
    ]

    metrics = service._retrieval_case_metrics(
        citations=citations,
        expected_file="src/orders.py",
        expected_lines={"start_line": 50, "end_line": 55},
    )

    assert metrics["relevant_hit"] is True
    assert metrics["first_relevant_rank"] == 2
    assert metrics["reciprocal_rank"] == 0.5
    assert metrics["file_hit"] is True
    assert metrics["line_hit"] is True
    assert metrics["line_overlap"] == 1.0
    assert metrics["citation_precision"] == pytest.approx(1 / 3)


def test_retrieval_case_file_only_hit_does_not_pass_expected_lines() -> None:
    service = EvaluationService(None)  # type: ignore[arg-type]
    citations = [
        {
            "file_path": "src/orders.py",
            "start_line": 1,
            "end_line": 20,
        }
    ]

    metrics = service._retrieval_case_metrics(
        citations=citations,
        expected_file="src/orders.py",
        expected_lines=[50, 55],
    )

    assert metrics["file_hit"] is True
    assert metrics["line_hit"] is False
    assert metrics["relevant_hit"] is False
    assert (
        service._retrieval_failure(
            citations,
            expected_file="src/orders.py",
            expected_lines=[50, 55],
        )
        == "expected_lines_not_retrieved"
    )


def test_retrieval_metrics_use_requested_k_and_rank_metrics() -> None:
    results = [
        SimpleNamespace(
            passed=True,
            latency_ms=100,
            failure_category=None,
            result_json={
                "metrics": {
                    "reciprocal_rank": 1.0,
                    "ndcg": 1.0,
                    "file_hit": True,
                    "lines_required": True,
                    "line_hit": True,
                    "line_overlap": 0.5,
                    "citation_precision": 0.25,
                }
            },
        ),
        SimpleNamespace(
            passed=False,
            latency_ms=300,
            failure_category="expected_file_not_retrieved",
            result_json={
                "metrics": {
                    "reciprocal_rank": 0.0,
                    "ndcg": 0.0,
                    "file_hit": False,
                    "lines_required": False,
                    "line_hit": None,
                    "line_overlap": None,
                    "citation_precision": 0.0,
                }
            },
        ),
    ]

    metrics = EvaluationService(None)._retrieval_metrics(  # type: ignore[arg-type]
        results,
        top_k=8,
    )

    assert metrics["primary_metric"] == "recall_at_8"
    assert metrics["recall_at_8"] == 0.5
    assert "recall_at_5" not in metrics
    assert metrics["mrr"] == 0.5
    assert metrics["ndcg"] == 0.5
    assert metrics["file_hit_rate"] == 0.5
    assert metrics["line_hit_rate"] == 1.0
    assert metrics["line_overlap"] == 0.5
    assert metrics["citation_precision"] == 0.125
    assert metrics["p50_latency_sec"] == 0.2
    assert metrics["p95_latency_sec"] == pytest.approx(0.29)


def test_fix_metrics_come_from_verification_evidence() -> None:
    verified = {
        "agent_status": "verified_success",
        "iterations": 1,
        "tool_calls": 4,
        "planner_tokens": 120,
        "total_tokens": 240,
        "test_result": {
            "baseline_reproduced": True,
            "patch_applied": True,
            "targeted": _test_result("passed"),
            "regression": _test_result("passed"),
        },
    }
    skipped = {
        "agent_status": "unverified_patch",
        "iterations": 2,
        "tool_calls": 6,
        "planner_tokens": 180,
        "total_tokens": 360,
        "test_result": {
            "baseline_reproduced": True,
            "patch_applied": True,
            "targeted": _test_result("skipped"),
            "regression": None,
        },
    }
    results = [
        SimpleNamespace(
            passed=True,
            result_json=verified,
            latency_ms=100,
            failure_category=None,
        ),
        SimpleNamespace(
            passed=False,
            result_json=skipped,
            latency_ms=900,
            failure_category="tests_not_run",
        ),
    ]

    metrics = EvaluationService(None)._fix_metrics(results)  # type: ignore[arg-type]

    assert metrics["primary_metric"] == "final_verified_fix_rate"
    assert metrics["verified_fix_at_1"] == 0.5
    assert metrics["final_verified_fix_rate"] == 0.5
    assert metrics["fix_success_rate"] == 0.5
    assert metrics["baseline_reproduced_rate"] == 1.0
    assert metrics["patch_apply_rate"] == 1.0
    assert metrics["regression_pass_rate"] == 0.5
    assert metrics["regression_rate"] == 0.0
    assert metrics["tests_skipped_rate"] == 0.5
    assert metrics["avg_iterations"] == 1.5
    assert metrics["avg_tool_calls"] == 5.0
    assert metrics["avg_planner_tokens"] == 150.0
    assert metrics["avg_total_tokens"] == 300.0
    assert metrics["total_tokens"] == 600
    assert metrics["estimated_total_cost_usd"] is None
    assert metrics["cost_estimation_status"] == "not_configured"
    assert metrics["p95_latency_sec"] == pytest.approx(0.86)


def test_fix_diff_rejects_changes_outside_case_allowlist() -> None:
    service = EvaluationService(None)  # type: ignore[arg-type]
    source_only = """diff --git a/src/cart.py b/src/cart.py
--- a/src/cart.py
+++ b/src/cart.py
"""
    test_change = source_only + """diff --git a/tests/test_cart.py b/tests/test_cart.py
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
"""

    assert service._changed_files_allowed(source_only, ["src/cart.py"]) is True
    assert service._changed_files_allowed(test_change, ["src/cart.py"]) is False


def _test_result(outcome: str) -> dict:
    if outcome == "passed":
        return {
            "tests_ran": True,
            "passed": True,
            "exit_code": 0,
        }
    if outcome == "skipped":
        return {
            "tests_ran": False,
            "passed": False,
            "exit_code": 0,
            "failure_kind": "skipped",
            "skipped_reason": "dependencies unavailable",
        }
    raise AssertionError(f"Unsupported test outcome: {outcome}")
