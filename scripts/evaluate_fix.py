#!/usr/bin/env python3
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"completed", "failed"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate CodeMate fix agent via Evaluation API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cases", default="scripts/eval_cases.json")
    parser.add_argument("--name", default="CLI fix eval")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--allow-skipped-tests",
        action="store_true",
        help="Count successful agent runs as passing even if sandbox tests were skipped.",
    )
    args = parser.parse_args()

    cases = load_cases(args.cases, "fix")
    if not cases:
        print("No fix cases found.")
        return 1

    evaluation_run = create_evaluation_run(
        args.base_url,
        name=args.name,
        cases=cases,
        require_tests_ran=not args.allow_skipped_tests,
    )
    completed_run = wait_for_evaluation_run(
        args.base_url,
        evaluation_run["id"],
        args.poll_interval,
        args.timeout,
    )

    print(json.dumps(to_report(completed_run), ensure_ascii=False, indent=2))
    return 0 if completed_run.get("status") == "completed" else 1


def create_evaluation_run(
    base_url: str,
    *,
    name: str,
    cases: list[dict[str, Any]],
    require_tests_ran: bool,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "require_tests_ran": require_tests_ran,
        "cases": normalize_cases(cases),
    }
    request = urllib.request.Request(
        f"{base_url}/evaluations/fix",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_evaluation_run(
    base_url: str,
    evaluation_run_id: str,
    interval: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        request = urllib.request.Request(f"{base_url}/evaluations/{evaluation_run_id}")
        with urllib.request.urlopen(request, timeout=60) as response:
            evaluation_run = json.loads(response.read().decode("utf-8"))
        if evaluation_run.get("status") in TERMINAL_STATUSES:
            return evaluation_run
        time.sleep(interval)
    raise TimeoutError(f"Evaluation run did not finish before timeout: {evaluation_run_id}")


def normalize_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if "repo_id" not in case or "issue" not in case:
            raise ValueError(f"Fix case {index} requires repo_id and issue.")
        normalized.append(
            {
                "case_id": case.get("case_id") or f"fix-{index}",
                "repo_id": case["repo_id"],
                "issue": case["issue"],
                "test_command": case.get("test_command"),
                "expected_status": case.get("expected_status", "success"),
                "expected_diff_contains": case.get("expected_diff_contains", []),
            }
        )
    return normalized


def to_report(evaluation_run: dict[str, Any]) -> dict[str, Any]:
    metrics = evaluation_run.get("metrics_json") or {}
    return {
        "evaluation_run_id": evaluation_run.get("id"),
        "status": evaluation_run.get("status"),
        "cases": evaluation_run.get("case_count", 0),
        "fix_success_rate": metrics.get("fix_success_rate", 0.0),
        "avg_tool_calls": metrics.get("avg_tool_calls", 0.0),
        "avg_latency_sec": metrics.get("avg_latency_sec", 0.0),
        "failure_distribution": metrics.get("failure_distribution", {}),
        "results": [result_summary(result) for result in evaluation_run.get("results", [])],
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    output = result.get("result_json") or {}
    return {
        "case_id": result.get("case_id"),
        "agent_run_id": result.get("agent_run_id"),
        "status": result.get("status"),
        "passed": result.get("passed"),
        "failure_category": result.get("failure_category"),
        "tool_calls": output.get("tool_calls") if isinstance(output, dict) else None,
        "latency_sec": round((result.get("latency_ms") or 0) / 1000, 3),
        "summary": output.get("summary") if isinstance(output, dict) else None,
    }


def load_cases(path: str, key: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get(key, [])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise
