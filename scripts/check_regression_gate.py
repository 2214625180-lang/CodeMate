#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluation_api_client import add_api_token_argument, json_headers  # noqa: E402
from evaluation_gate_summary import default_summary_output_path, write_gate_summary  # noqa: E402
from export_eval_report import export_artifact_files  # noqa: E402


EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_INCONCLUSIVE = 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CodeMate regression gate via Evaluation API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    add_api_token_argument(parser)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument("--artifact-dir", default="artifacts/evaluations")
    parser.add_argument(
        "--summary-output",
        help=(
            "Write a Markdown gate summary to this path. Defaults to "
            "<artifact-dir>/<candidate-run-id>-gate-summary.md."
        ),
    )
    parser.add_argument(
        "--no-github-step-summary",
        action="store_true",
        help="Do not append the Markdown gate summary to $GITHUB_STEP_SUMMARY.",
    )
    parser.add_argument(
        "--no-export-artifacts",
        action="store_true",
        help="Skip exporting candidate run JSON/Markdown artifacts after the gate check.",
    )
    parser.add_argument(
        "--no-agent-steps",
        action="store_true",
        help="Exclude agent step payloads from exported artifacts.",
    )
    parser.add_argument(
        "--max-payload-chars",
        type=int,
        default=12000,
        help="Maximum JSON characters kept for each large artifact payload before truncation.",
    )
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
        api_token=args.api_token,
    )
    artifact_paths: dict[str, str] = {}
    if not args.no_export_artifacts:
        artifact_paths = export_artifact_files(
            base_url=args.base_url,
            run_id=args.candidate_run_id,
            output_dir=args.artifact_dir,
            include_agent_steps=not args.no_agent_steps,
            max_payload_chars=args.max_payload_chars,
            api_token=args.api_token,
        )

    summary_output = args.summary_output or default_summary_output_path(
        artifact_dir=args.artifact_dir,
        candidate_run_id=args.candidate_run_id,
    )
    artifacts_for_summary = dict(artifact_paths)
    artifacts_for_summary["gate_summary"] = summary_output
    summary_paths = write_gate_summary(
        gate_result=gate_result,
        artifact_paths=artifacts_for_summary,
        output_path=summary_output,
        append_github_step_summary=not args.no_github_step_summary,
    )
    if "markdown" in summary_paths:
        artifact_paths["gate_summary"] = summary_paths["markdown"]

    output = gate_result if args.full else to_summary(gate_result)
    if artifact_paths:
        output["artifact_paths"] = artifact_paths
    if summary_paths:
        output["summary_paths"] = summary_paths
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code(gate_result)


def fetch_gate_result(
    *,
    base_url: str,
    dataset_id: str,
    candidate_run_id: str,
    api_token: str | None = None,
) -> dict[str, Any]:
    encoded_dataset_id = urllib.parse.quote(dataset_id, safe="")
    query = urllib.parse.urlencode({"candidate_run_id": candidate_run_id})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/evaluations/datasets/{encoded_dataset_id}/gate?{query}",
        headers=json_headers(api_token),
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
        "baseline_dataset_snapshot_id": baseline_run.get("dataset_snapshot_id"),
        "candidate_dataset_snapshot_id": candidate_run.get("dataset_snapshot_id"),
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
