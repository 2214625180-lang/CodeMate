#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_INCONCLUSIVE = 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CodeMate regression gate via Evaluation API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the full gate API response instead of the compact CI summary.",
    )
    args = parser.parse_args()

    gate_result = fetch_gate_result(
        base_url=args.base_url,
        dataset_id=args.dataset_id,
        candidate_run_id=args.candidate_run_id,
    )
    print(json.dumps(gate_result if args.full else to_summary(gate_result), ensure_ascii=False, indent=2))
    return exit_code(gate_result)


def fetch_gate_result(
    *,
    base_url: str,
    dataset_id: str,
    candidate_run_id: str,
) -> dict[str, Any]:
    encoded_dataset_id = urllib.parse.quote(dataset_id, safe="")
    query = urllib.parse.urlencode({"candidate_run_id": candidate_run_id})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/evaluations/datasets/{encoded_dataset_id}/gate?{query}"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def to_summary(gate_result: dict[str, Any]) -> dict[str, Any]:
    comparison = gate_result.get("comparison") or {}
    summary = comparison.get("summary") or {}
    primary_metric_delta = summary.get("primary_metric_delta") or {}
    dataset = gate_result.get("dataset") or {}
    baseline_run = gate_result.get("baseline_run") or {}
    candidate_run = gate_result.get("candidate_run") or {}

    return {
        "status": gate_result.get("status"),
        "dataset_id": dataset.get("id"),
        "dataset_name": dataset.get("name"),
        "baseline_run_id": baseline_run.get("id"),
        "candidate_run_id": candidate_run.get("id"),
        "primary_metric": comparison.get("primary_metric"),
        "primary_metric_delta": primary_metric_delta.get("delta"),
        "regressions": summary.get("regressions"),
        "improvements": summary.get("improvements"),
        "checks": [
            {
                "name": check.get("name"),
                "passed": check.get("passed"),
                "observed": check.get("observed"),
                "threshold": check.get("threshold"),
                "message": check.get("message"),
            }
            for check in gate_result.get("checks", [])
        ],
    }


def exit_code(gate_result: dict[str, Any]) -> int:
    status = gate_result.get("status")
    if status == "passed":
        return EXIT_PASSED
    if status == "failed":
        return EXIT_FAILED
    return EXIT_INCONCLUSIVE


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        sys.exit(EXIT_INCONCLUSIVE)
    except urllib.error.URLError as exc:
        print(f"Failed to reach Evaluation API: {exc}", file=sys.stderr)
        sys.exit(EXIT_INCONCLUSIVE)
