#!/usr/bin/env python3
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluation_api_client import add_api_token_argument, json_headers  # noqa: E402
from check_regression_gate import (  # noqa: E402
    EXIT_INCONCLUSIVE,
    exit_code,
    fetch_gate_result,
    to_summary,
)
from backfill_dataset_snapshots_api import export_api_backfill_report_files  # noqa: E402
from evaluation_gate_summary import (  # noqa: E402
    default_summary_output_path,
    write_gate_summary,
    write_timeout_summary,
)
from export_eval_history_report import export_history_report_files  # noqa: E402
from export_eval_report import export_artifact_files  # noqa: E402


TERMINAL_STATUSES = {"completed", "failed"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a CodeMate evaluation run from a benchmark dataset, wait for it, "
            "check the regression gate, and export CI artifacts."
        )
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    add_api_token_argument(parser)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--name", help="Optional candidate evaluation run name.")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Retrieval top_k for retrieval datasets. Ignored for fix datasets.",
    )
    parser.add_argument(
        "--allow-skipped-tests",
        action="store_true",
        help="For fix datasets, do not require successful runs to execute tests.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=1800,
        help="Maximum time to wait for the evaluation run before exiting inconclusive.",
    )
    parser.add_argument(
        "--poll-interval-sec",
        type=float,
        default=5.0,
        help="Seconds between evaluation run status polls.",
    )
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
        help="Skip exporting candidate run JSON/Markdown artifacts.",
    )
    parser.add_argument(
        "--no-export-history-report",
        action="store_true",
        help="Skip exporting dataset history trend JSON/Markdown artifacts.",
    )
    parser.add_argument(
        "--snapshot-backfill-audit",
        action="store_true",
        help="Run an API dry-run dataset snapshot backfill audit and export JSON/Markdown artifacts.",
    )
    parser.add_argument(
        "--snapshot-backfill-limit",
        type=int,
        default=0,
        help="Maximum runs to scan for the snapshot backfill audit. Defaults to all.",
    )
    parser.add_argument(
        "--snapshot-backfill-no-create-missing-snapshots",
        action="store_true",
        help="For the audit, only bind to existing snapshots; do not preview creating missing snapshots.",
    )
    parser.add_argument(
        "--snapshot-backfill-report-stem",
        help="Custom filename stem for snapshot backfill audit artifacts.",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=50,
        help="Maximum filtered history runs to include in exported trend reports.",
    )
    parser.add_argument(
        "--history-created-after",
        help="Only include history runs created at or after this ISO datetime.",
    )
    parser.add_argument(
        "--history-created-before",
        help="Only include history runs created at or before this ISO datetime.",
    )
    parser.add_argument(
        "--history-status",
        choices=["running", "completed", "failed"],
        help="Only include history runs with this run status.",
    )
    parser.add_argument(
        "--history-gate-status",
        choices=["passed", "failed", "inconclusive", "not_evaluated"],
        help="Only include history runs with this gate status.",
    )
    parser.add_argument(
        "--history-provider",
        help="Case-insensitive provider substring filter for exported trend reports.",
    )
    parser.add_argument(
        "--history-model",
        help="Case-insensitive model substring filter for exported trend reports.",
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

    candidate_run = create_dataset_run(
        base_url=args.base_url,
        dataset_id=args.dataset_id,
        name=args.name,
        top_k=args.top_k,
        require_tests_ran=not args.allow_skipped_tests,
        api_token=args.api_token,
    )
    candidate_run_id = candidate_run["id"]
    print(
        f"Created evaluation run {candidate_run_id} "
        f"(status={candidate_run.get('status', 'unknown')})",
        file=sys.stderr,
    )

    final_run, timed_out = wait_for_evaluation_run(
        base_url=args.base_url,
        evaluation_run_id=candidate_run_id,
        timeout_sec=args.timeout_sec,
        poll_interval_sec=args.poll_interval_sec,
        api_token=args.api_token,
    )

    artifact_paths: dict[str, str] = {}
    if not args.no_export_artifacts:
        artifact_paths = export_artifact_files(
            base_url=args.base_url,
            run_id=candidate_run_id,
            output_dir=args.artifact_dir,
            include_agent_steps=not args.no_agent_steps,
            max_payload_chars=args.max_payload_chars,
            api_token=args.api_token,
        )

    if not args.no_export_history_report:
        artifact_paths.update(
            export_history_report_files(
                base_url=args.base_url,
                dataset_id=args.dataset_id,
                output_dir=args.artifact_dir,
                limit=args.history_limit,
                created_after=args.history_created_after,
                created_before=args.history_created_before,
                status=args.history_status,
                gate_status=args.history_gate_status,
                provider=args.history_provider,
                model=args.history_model,
                api_token=args.api_token,
            )
        )

    if args.snapshot_backfill_audit:
        artifact_paths.update(
            export_api_backfill_report_files(
                base_url=args.base_url,
                dataset_id=args.dataset_id,
                output_dir=args.artifact_dir,
                limit=args.snapshot_backfill_limit if args.snapshot_backfill_limit > 0 else None,
                dry_run=True,
                create_missing_snapshots=not args.snapshot_backfill_no_create_missing_snapshots,
                stem=args.snapshot_backfill_report_stem,
                api_token=args.api_token,
            )
        )

    summary_output = args.summary_output or default_summary_output_path(
        artifact_dir=args.artifact_dir,
        candidate_run_id=candidate_run_id,
    )

    if timed_out:
        artifacts_for_summary = dict(artifact_paths)
        artifacts_for_summary["gate_summary"] = summary_output
        summary_paths = write_timeout_summary(
            dataset_id=args.dataset_id,
            candidate_run_id=candidate_run_id,
            candidate_run_status=final_run.get("status"),
            artifact_paths=artifacts_for_summary,
            output_path=summary_output,
            append_github_step_summary=not args.no_github_step_summary,
        )
        if "markdown" in summary_paths:
            artifact_paths["gate_summary"] = summary_paths["markdown"]
        print(
            json.dumps(
                {
                    "status": "timeout",
                    "dataset_id": args.dataset_id,
                    "candidate_run_id": candidate_run_id,
                    "candidate_run_status": final_run.get("status"),
                    "artifact_paths": artifact_paths,
                    "summary_paths": summary_paths,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_INCONCLUSIVE

    gate_result = fetch_gate_result(
        base_url=args.base_url,
        dataset_id=args.dataset_id,
        candidate_run_id=candidate_run_id,
        api_token=args.api_token,
    )
    artifacts_for_summary = dict(artifact_paths)
    artifacts_for_summary["gate_summary"] = summary_output
    summary_paths = write_gate_summary(
        gate_result=gate_result,
        artifact_paths=artifacts_for_summary,
        output_path=summary_output,
        append_github_step_summary=not args.no_github_step_summary,
        candidate_run_status=final_run.get("status"),
    )
    if "markdown" in summary_paths:
        artifact_paths["gate_summary"] = summary_paths["markdown"]
    output = gate_result if args.full else to_summary(gate_result)
    output["candidate_run_status"] = final_run.get("status")
    if artifact_paths:
        output["artifact_paths"] = artifact_paths
    if summary_paths:
        output["summary_paths"] = summary_paths
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code(gate_result)


def create_dataset_run(
    *,
    base_url: str,
    dataset_id: str,
    name: str | None,
    top_k: int,
    require_tests_ran: bool,
    api_token: str | None = None,
) -> dict[str, Any]:
    encoded_dataset_id = urllib.parse.quote(dataset_id, safe="")
    payload: dict[str, Any] = {
        "top_k": top_k,
        "require_tests_ran": require_tests_ran,
    }
    if name:
        payload["name"] = name
    return request_json(
        f"{base_url.rstrip('/')}/evaluations/datasets/{encoded_dataset_id}/run",
        method="POST",
        payload=payload,
        api_token=api_token,
    )


def wait_for_evaluation_run(
    *,
    base_url: str,
    evaluation_run_id: str,
    timeout_sec: int,
    poll_interval_sec: float,
    api_token: str | None = None,
) -> tuple[dict[str, Any], bool]:
    deadline = time.monotonic() + timeout_sec
    last_status: str | None = None
    latest_run: dict[str, Any] = {}

    while True:
        latest_run = fetch_evaluation_run(
            base_url=base_url,
            evaluation_run_id=evaluation_run_id,
            api_token=api_token,
        )
        status = latest_run.get("status")
        if status != last_status:
            print(
                f"Evaluation run {evaluation_run_id} status: {status or 'unknown'}",
                file=sys.stderr,
            )
            last_status = status
        if status in TERMINAL_STATUSES:
            return latest_run, False
        if time.monotonic() >= deadline:
            return latest_run, True
        time.sleep(max(0.1, poll_interval_sec))


def fetch_evaluation_run(
    *,
    base_url: str,
    evaluation_run_id: str,
    api_token: str | None = None,
) -> dict[str, Any]:
    encoded_run_id = urllib.parse.quote(evaluation_run_id, safe="")
    return request_json(
        f"{base_url.rstrip('/')}/evaluations/{encoded_run_id}",
        api_token=api_token,
    )


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    headers = json_headers(api_token, content_type=payload is not None)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        sys.exit(EXIT_INCONCLUSIVE)
    except urllib.error.URLError as exc:
        print(f"Failed to reach Evaluation API: {exc}", file=sys.stderr)
        sys.exit(EXIT_INCONCLUSIVE)
