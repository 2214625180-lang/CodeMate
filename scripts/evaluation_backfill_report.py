import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_backfill_report(
    *,
    result: dict[str, Any],
    dataset_id: str | None,
    run_id: str | None = None,
    task_type: str | None = None,
    limit: int | None = None,
    create_missing_snapshots: bool = True,
) -> dict[str, Any]:
    return {
        "report_version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": "dataset_snapshot_backfill",
        "parameters": {
            "dataset_id": dataset_id,
            "run_id": run_id,
            "task_type": task_type,
            "limit": limit,
            "dry_run": result.get("dry_run"),
            "create_missing_snapshots": create_missing_snapshots,
        },
        "result": result,
    }


def export_backfill_report_files(
    *,
    report: dict[str, Any],
    output_dir: str,
    stem: str | None = None,
) -> dict[str, str]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    file_stem = stem or backfill_report_stem(report)
    paths = {
        "backfill_json": output_root / f"{file_stem}.json",
        "backfill_markdown": output_root / f"{file_stem}.md",
    }
    path_strings = {key: str(path) for key, path in paths.items()}
    result = report.get("result")
    if isinstance(result, dict):
        result["artifact_paths"] = path_strings
    write_output(render_backfill_report(report, "json"), str(paths["backfill_json"]))
    write_output(render_backfill_report(report, "markdown"), str(paths["backfill_markdown"]))
    return path_strings


def render_backfill_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if output_format == "markdown":
        return render_markdown(report)
    raise ValueError(f"Unsupported output format: {output_format}")


def render_markdown(report: dict[str, Any]) -> str:
    parameters = report.get("parameters") or {}
    result = report.get("result") or {}
    details = result.get("details") or []

    lines = [
        "# Dataset Snapshot Backfill Report",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        row("Generated At", report.get("generated_at")),
        row("Dataset", parameters.get("dataset_id") or "all"),
        row("Run", parameters.get("run_id") or "all"),
        row("Task Type", parameters.get("task_type") or "all"),
        row("Limit", parameters.get("limit") or "all"),
        row("Mode", "dry run" if result.get("dry_run") else "applied"),
        row("Create Missing Snapshots", parameters.get("create_missing_snapshots")),
        row("Scanned Runs", result.get("scanned")),
        row("Backfilled Runs", result.get("backfilled")),
        row("Skipped Runs", result.get("skipped")),
        row("Created Snapshots", result.get("created_snapshots")),
        "",
        "## Status Counts",
        "",
        status_counts_table(result.get("status_counts") or {}),
        "",
        "## Details",
        "",
        details_table(details),
    ]
    return "\n".join(lines).rstrip() + "\n"


def backfill_report_stem(report: dict[str, Any]) -> str:
    parameters = report.get("parameters") or {}
    dataset_id = str(parameters.get("dataset_id") or "all-datasets")
    mode = "dry-run" if (report.get("result") or {}).get("dry_run") else "applied"
    return f"{dataset_id}-snapshot-backfill-{mode}"


def status_counts_table(counts: dict[str, Any]) -> str:
    if not counts:
        return "_No statuses recorded._"
    lines = ["| Status | Count |", "| --- | ---: |"]
    for status, count in sorted(counts.items()):
        lines.append(f"| {escape_table(status)} | {escape_table(count)} |")
    return "\n".join(lines)


def details_table(details: list[dict[str, Any]]) -> str:
    if not details:
        return "_No per-run details recorded._"
    lines = [
        "| Run | Status | Dataset Version | Snapshot | Created Snapshot | Reason |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for item in details[:50]:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(item.get("run_id")),
                    escape_table(item.get("status")),
                    escape_table(item.get("dataset_version")),
                    escape_table(item.get("dataset_snapshot_id") or item.get("snapshot_id") or "n/a"),
                    escape_table(item.get("created_snapshot_id") or "n/a"),
                    escape_table(short_text(item.get("reason") or "", 120)),
                ]
            )
            + " |"
        )
    if len(details) > 50:
        lines.append(f"| ... | truncated |  |  |  | {len(details) - 50} more details |")
    return "\n".join(lines)


def row(label: str, value: Any) -> str:
    return f"| {escape_table(label)} | {escape_table(format_value(value))} |"


def write_output(content: str, output_path: str | None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


def format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def short_text(value: Any, limit: int) -> str:
    text = format_value(value).replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def escape_table(value: Any) -> str:
    return format_value(value).replace("|", "\\|").replace("\n", "<br>")
