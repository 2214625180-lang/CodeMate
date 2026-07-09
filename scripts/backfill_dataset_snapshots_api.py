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

from evaluation_backfill_report import build_backfill_report, export_backfill_report_files  # noqa: E402
from evaluation_api_client import add_api_token_argument, json_headers  # noqa: E402


EXIT_OK = 0
EXIT_API_ERROR = 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run dataset snapshot backfill through the CodeMate Evaluation API "
            "and export JSON/Markdown audit reports."
        )
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    add_api_token_argument(parser)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--run-id", help="Only backfill one evaluation run.")
    parser.add_argument(
        "--task-type",
        choices=["retrieval", "fix"],
        help="Only backfill runs with this task type.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum candidate runs to scan. Defaults to all.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Preview changes without applying them. This is the default.",
    )
    mode.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Apply the backfill through the API.",
    )
    parser.add_argument(
        "--no-create-missing-snapshots",
        action="store_true",
        help="Only bind runs to existing snapshots; do not create missing historical snapshots.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the full audit report JSON instead of the compact API result.",
    )
    parser.add_argument(
        "--artifact-dir",
        default="artifacts/evaluations",
        help="Directory for JSON/Markdown migration reports.",
    )
    parser.add_argument(
        "--report-stem",
        help="Custom filename stem for exported reports.",
    )
    parser.add_argument(
        "--no-export-report",
        action="store_true",
        help="Do not write JSON/Markdown backfill reports.",
    )
    args = parser.parse_args()

    limit = args.limit if args.limit > 0 else None
    create_missing_snapshots = not args.no_create_missing_snapshots
    result = request_backfill(
        base_url=args.base_url,
        dataset_id=args.dataset_id,
        run_id=args.run_id,
        task_type=args.task_type,
        limit=limit,
        dry_run=args.dry_run,
        create_missing_snapshots=create_missing_snapshots,
        include_details=True,
        api_token=args.api_token,
    )
    report = build_backfill_report(
        result=result,
        dataset_id=args.dataset_id,
        run_id=args.run_id,
        task_type=args.task_type,
        limit=limit,
        create_missing_snapshots=create_missing_snapshots,
    )
    if not args.no_export_report:
        result["artifact_paths"] = export_backfill_report_files(
            report=report,
            output_dir=args.artifact_dir,
            stem=args.report_stem,
        )
        report["result"] = result

    output = report if args.full else result
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return EXIT_OK


def export_api_backfill_report_files(
    *,
    base_url: str,
    dataset_id: str,
    output_dir: str,
    run_id: str | None = None,
    task_type: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    create_missing_snapshots: bool = True,
    stem: str | None = None,
    api_token: str | None = None,
) -> dict[str, str]:
    result = request_backfill(
        base_url=base_url,
        dataset_id=dataset_id,
        run_id=run_id,
        task_type=task_type,
        limit=limit,
        dry_run=dry_run,
        create_missing_snapshots=create_missing_snapshots,
        include_details=True,
        api_token=api_token,
    )
    report = build_backfill_report(
        result=result,
        dataset_id=dataset_id,
        run_id=run_id,
        task_type=task_type,
        limit=limit,
        create_missing_snapshots=create_missing_snapshots,
    )
    paths = export_backfill_report_files(
        report=report,
        output_dir=output_dir,
        stem=stem,
    )
    result["artifact_paths"] = paths
    return paths


def request_backfill(
    *,
    base_url: str,
    dataset_id: str,
    run_id: str | None,
    task_type: str | None,
    limit: int | None,
    dry_run: bool,
    create_missing_snapshots: bool,
    include_details: bool,
    api_token: str | None = None,
) -> dict[str, Any]:
    encoded_dataset_id = urllib.parse.quote(dataset_id, safe="")
    payload: dict[str, Any] = {
        "dry_run": dry_run,
        "create_missing_snapshots": create_missing_snapshots,
        "include_details": include_details,
    }
    if run_id:
        payload["run_id"] = run_id
    if task_type:
        payload["task_type"] = task_type
    if limit is not None:
        payload["limit"] = limit

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/evaluations/datasets/{encoded_dataset_id}/snapshots/backfill",
        data=json.dumps(payload).encode("utf-8"),
        headers=json_headers(api_token, content_type=True),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        sys.exit(EXIT_API_ERROR)
    except urllib.error.URLError as exc:
        print(f"Failed to reach Evaluation API: {exc}", file=sys.stderr)
        sys.exit(EXIT_API_ERROR)
