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


def main() -> int:
    parser = argparse.ArgumentParser(description="Export CodeMate evaluation history trend report.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    add_api_token_argument(parser)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--output", help="Write report to this path. Defaults to stdout.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum filtered runs to include.")
    parser.add_argument("--created-after", help="Only include runs created at or after this ISO datetime.")
    parser.add_argument("--created-before", help="Only include runs created at or before this ISO datetime.")
    parser.add_argument("--status", choices=["running", "completed", "failed"])
    parser.add_argument(
        "--gate-status",
        choices=["passed", "failed", "inconclusive", "not_evaluated"],
    )
    parser.add_argument("--provider", help="Case-insensitive provider substring filter.")
    parser.add_argument("--model", help="Case-insensitive model substring filter.")
    args = parser.parse_args()

    history = fetch_history(
        base_url=args.base_url,
        dataset_id=args.dataset_id,
        limit=args.limit,
        created_after=args.created_after,
        created_before=args.created_before,
        status=args.status,
        gate_status=args.gate_status,
        provider=args.provider,
        model=args.model,
        api_token=args.api_token,
    )
    rendered = render_history_report(history, args.format)
    write_output(rendered, args.output)
    return 0


def export_history_report_files(
    *,
    base_url: str,
    dataset_id: str,
    output_dir: str,
    limit: int = 50,
    created_after: str | None = None,
    created_before: str | None = None,
    status: str | None = None,
    gate_status: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_token: str | None = None,
) -> dict[str, str]:
    history = fetch_history(
        base_url=base_url,
        dataset_id=dataset_id,
        limit=limit,
        created_after=created_after,
        created_before=created_before,
        status=status,
        gate_status=gate_status,
        provider=provider,
        model=model,
        api_token=api_token,
    )
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    stem = history_report_stem(history)
    paths = {
        "history_json": output_root / f"{stem}.json",
        "history_markdown": output_root / f"{stem}.md",
    }
    write_output(render_history_report(history, "json"), str(paths["history_json"]))
    write_output(render_history_report(history, "markdown"), str(paths["history_markdown"]))
    return {key: str(path) for key, path in paths.items()}


def fetch_history(
    *,
    base_url: str,
    dataset_id: str,
    limit: int,
    created_after: str | None = None,
    created_before: str | None = None,
    status: str | None = None,
    gate_status: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    encoded_dataset_id = urllib.parse.quote(dataset_id, safe="")
    params = {"limit": str(limit)}
    optional_params = {
        "created_after": created_after,
        "created_before": created_before,
        "status": status,
        "gate_status": gate_status,
        "provider": provider,
        "model": model,
    }
    params.update({key: value for key, value in optional_params.items() if value})
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/evaluations/datasets/{encoded_dataset_id}/history?{query}",
        headers=json_headers(api_token),
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def render_history_report(history: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(
            {
                "report_version": "1",
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    if output_format == "markdown":
        return render_markdown(history)
    raise ValueError(f"Unsupported output format: {output_format}")


def render_markdown(history: dict[str, Any]) -> str:
    dataset = history.get("dataset") or {}
    summary = history.get("summary") or {}
    filters = history.get("filters") or {}
    runs = history.get("runs") or []
    failure_distribution = aggregate_failure_distribution(runs)

    lines = [
        f"# Evaluation Trend Report: {escape_markdown(str(dataset.get('name') or dataset.get('id') or 'Dataset'))}",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        row("Dataset", dataset_label(dataset)),
        row("Task Type", dataset.get("task_type")),
        row("Dataset Version", dataset.get("version")),
        row("Baseline Run", history.get("baseline_run_id") or "not configured"),
        row("Primary Metric", metric_label(history.get("primary_metric_name"))),
        row("Latest Metric", format_percent(summary.get("latest_primary_metric"))),
        row("Latest Delta", format_delta(summary.get("latest_primary_metric_delta"))),
        row("Completed Runs", f"{format_value(summary.get('completed_count'))}/{format_value(summary.get('run_count', len(runs)))}"),
        row("Average Latency", format_seconds(summary.get("avg_latency_sec"))),
        row("Average Tool Calls", format_nullable_number(summary.get("avg_tool_calls"))),
        "",
        "## Filters",
        "",
        "| Filter | Value |",
        "| --- | --- |",
        row("Limit", filters.get("limit")),
        row("Created After", filters.get("created_after") or "all"),
        row("Created Before", filters.get("created_before") or "all"),
        row("Run Status", filters.get("status") or "all"),
        row("Gate Status", filters.get("gate_status") or "all"),
        row("Provider", filters.get("provider") or "all"),
        row("Model", filters.get("model") or "all"),
        "",
        "## Gate Status Counts",
        "",
        gate_status_table(history.get("gate_status_counts") or {}),
        "",
        "## Failure Distribution",
        "",
        failure_distribution_table(failure_distribution),
        "",
        "## Runs",
        "",
        runs_table(runs),
    ]
    return "\n".join(lines).rstrip() + "\n"


def history_report_stem(history: dict[str, Any]) -> str:
    dataset = history.get("dataset") or {}
    dataset_id = str(dataset.get("id") or "dataset")
    return f"{dataset_id}-trend"


def dataset_label(dataset: dict[str, Any]) -> str:
    dataset_id = dataset.get("id")
    name = dataset.get("name")
    if dataset_id and name:
        return f"{name} ({dataset_id})"
    return name or dataset_id or "n/a"


def gate_status_table(counts: dict[str, Any]) -> str:
    rows = [
        ("passed", counts.get("passed", 0)),
        ("failed", counts.get("failed", 0)),
        ("inconclusive", counts.get("inconclusive", 0)),
        ("not_evaluated", counts.get("not_evaluated", 0)),
    ]
    lines = ["| Gate Status | Count |", "| --- | ---: |"]
    lines.extend(f"| {escape_table(status)} | {escape_table(count)} |" for status, count in rows)
    return "\n".join(lines)


def failure_distribution_table(failures: dict[str, int]) -> str:
    if not failures:
        return "_No failures in the filtered history._"
    lines = ["| Failure Category | Count |", "| --- | ---: |"]
    for category, count in sorted(failures.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {escape_table(category)} | {count} |")
    return "\n".join(lines)


def runs_table(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "_No runs matched the selected filters._"
    lines = [
        "| Run | Snapshot | Status | Gate | Metric | Delta | Latency | Regressions | Provider | Model | Created |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for run in runs:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(run.get("name") or run.get("id")),
                    escape_table(run.get("dataset_snapshot_id") or "n/a"),
                    escape_table(run.get("status")),
                    escape_table(run.get("gate_status")),
                    escape_table(format_percent(run.get("primary_metric_value"))),
                    escape_table(format_delta(run.get("primary_metric_delta"))),
                    escape_table(format_seconds(run.get("avg_latency_sec"))),
                    escape_table(run.get("regressions") if run.get("regressions") is not None else "n/a"),
                    escape_table(run.get("provider") or "n/a"),
                    escape_table(run.get("model") or "n/a"),
                    escape_table(run.get("created_at")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def aggregate_failure_distribution(runs: list[dict[str, Any]]) -> dict[str, int]:
    failures: dict[str, int] = {}
    for run in runs:
        distribution = run.get("failure_distribution")
        if not isinstance(distribution, dict):
            continue
        for category, count in distribution.items():
            if isinstance(count, int | float):
                failures[str(category)] = failures.get(str(category), 0) + int(count)
    return failures


def row(label: str, value: Any) -> str:
    return f"| {escape_table(label)} | {escape_table(format_value(value))} |"


def metric_label(metric_name: Any) -> str:
    labels = {
        "fix_success_rate": "Fix Success Rate",
        "final_verified_fix_rate": "Final Verified Fix Rate",
        "avg_latency_sec": "Avg Latency",
        "avg_tool_calls": "Avg Tool Calls",
    }
    normalized = str(metric_name)
    if normalized.startswith("recall_at_") and normalized.removeprefix("recall_at_").isdigit():
        return f"Recall@{normalized.removeprefix('recall_at_')}"
    return labels.get(normalized, str(metric_name or "n/a"))


def format_percent(value: Any) -> str:
    if not isinstance(value, int | float):
        return "n/a"
    return f"{round(value * 1000) / 10:g}%"


def format_delta(value: Any) -> str:
    if not isinstance(value, int | float):
        return "n/a"
    prefix = "+" if value > 0 else ""
    return f"{prefix}{round(value * 1000) / 10:g}%"


def format_seconds(value: Any) -> str:
    if not isinstance(value, int | float):
        return "n/a"
    return f"{round(value * 1000) / 1000:g}s"


def format_nullable_number(value: Any) -> str:
    if not isinstance(value, int | float):
        return "n/a"
    return f"{round(value * 100) / 100:g}"


def format_value(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return str(value)


def escape_table(value: Any) -> str:
    return escape_markdown(format_value(value)).replace("|", "\\|").replace("\n", " ")


def escape_markdown(value: str) -> str:
    return value.replace("`", "\\`")


def write_output(content: str, output_path: str | None) -> None:
    if not output_path:
        print(content, end="")
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as exc:
        print(f"Failed to reach Evaluation API: {exc}", file=sys.stderr)
        sys.exit(2)
