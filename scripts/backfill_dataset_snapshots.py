#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluation_backfill_report import build_backfill_report, export_backfill_report_files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill evaluation run dataset_snapshot_id from persisted request cases."
    )
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL before loading the backend settings.",
    )
    parser.add_argument("--dataset-id", help="Only backfill runs for this benchmark dataset.")
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing them.",
    )
    parser.add_argument(
        "--no-create-missing-snapshots",
        action="store_true",
        help="Only bind runs to existing snapshots; do not create missing historical snapshots.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include per-run details in the JSON output.",
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

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    backend_root = Path(__file__).resolve().parents[1] / "backend"
    sys.path.insert(0, str(backend_root))

    from app.core.database import SessionLocal, init_db  # noqa: E402
    from app.services.evaluation_snapshot_backfill_service import (  # noqa: E402
        EvaluationSnapshotBackfillService,
    )

    init_db()
    db = SessionLocal()
    try:
        result = EvaluationSnapshotBackfillService(db).backfill(
            dataset_id=args.dataset_id,
            run_id=args.run_id,
            task_type=args.task_type,
            limit=args.limit if args.limit > 0 else None,
            dry_run=args.dry_run,
            create_missing_snapshots=not args.no_create_missing_snapshots,
            include_details=args.full,
        )
        report = build_backfill_report(
            result=result,
            dataset_id=args.dataset_id,
            run_id=args.run_id,
            task_type=args.task_type,
            limit=args.limit if args.limit > 0 else None,
            create_missing_snapshots=not args.no_create_missing_snapshots,
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
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
