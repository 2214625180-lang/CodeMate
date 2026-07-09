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
    parser = argparse.ArgumentParser(description="Export CodeMate evaluation run artifact.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    add_api_token_argument(parser)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument(
        "--output",
        help="Write artifact to this path. Defaults to stdout.",
    )
    parser.add_argument(
        "--no-agent-steps",
        action="store_true",
        help="Exclude agent step payloads from the exported artifact.",
    )
    parser.add_argument(
        "--max-payload-chars",
        type=int,
        default=12000,
        help="Maximum JSON characters kept for each large payload before truncation.",
    )
    args = parser.parse_args()

    artifact = fetch_artifact(
        base_url=args.base_url,
        run_id=args.run_id,
        include_agent_steps=not args.no_agent_steps,
        max_payload_chars=args.max_payload_chars,
        api_token=args.api_token,
    )
    rendered = render_artifact(artifact, args.format)
    write_output(rendered, args.output)
    return 0


def export_artifact_files(
    *,
    base_url: str,
    run_id: str,
    output_dir: str,
    include_agent_steps: bool = True,
    max_payload_chars: int = 12000,
    api_token: str | None = None,
) -> dict[str, str]:
    artifact = fetch_artifact(
        base_url=base_url,
        run_id=run_id,
        include_agent_steps=include_agent_steps,
        max_payload_chars=max_payload_chars,
        api_token=api_token,
    )
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_root / f"{run_id}.json",
        "markdown": output_root / f"{run_id}.md",
    }
    write_output(render_artifact(artifact, "json"), str(paths["json"]))
    write_output(render_artifact(artifact, "markdown"), str(paths["markdown"]))
    return {key: str(path) for key, path in paths.items()}


def fetch_artifact(
    *,
    base_url: str,
    run_id: str,
    include_agent_steps: bool,
    max_payload_chars: int,
    api_token: str | None = None,
) -> dict[str, Any]:
    encoded_run_id = urllib.parse.quote(run_id, safe="")
    query = urllib.parse.urlencode(
        {
            "include_agent_steps": str(include_agent_steps).lower(),
            "max_payload_chars": max_payload_chars,
        }
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/evaluations/{encoded_run_id}/artifact?{query}",
        headers=json_headers(api_token),
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def render_artifact(artifact: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    if output_format == "markdown":
        return render_markdown(artifact)
    raise ValueError(f"Unsupported output format: {output_format}")


def render_markdown(artifact: dict[str, Any]) -> str:
    run = artifact.get("run") or {}
    summary = artifact.get("summary") or {}
    metrics = summary.get("metrics") or run.get("metrics_json") or {}
    cases = artifact.get("cases") or []
    title = run.get("name") or run.get("id") or "Evaluation Run"

    lines = [
        f"# Evaluation Report: {escape_markdown(str(title))}",
        "",
        "## Run Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        row("Run ID", run.get("id")),
        row("Task Type", run.get("task_type")),
        row("Status", run.get("status")),
        row("Dataset", dataset_label(run)),
        row("Dataset Snapshot", run.get("dataset_snapshot_id")),
        row("Created At", run.get("created_at")),
        row("Finished At", run.get("finished_at")),
        row("Cases", summary.get("cases", run.get("case_count"))),
        row("Passed", summary.get("passed", run.get("passed_count"))),
        row("Failed", summary.get("failed", run.get("failed_count"))),
        row("Providers", join_values(summary.get("providers"))),
        row("Models", join_values(summary.get("models"))),
        "",
        "## Metrics",
        "",
        metrics_table(metrics),
        "",
        "## Failure Distribution",
        "",
        failure_table(summary.get("failure_distribution") or metrics.get("failure_distribution") or {}),
        "",
        "## Cases",
        "",
        cases_table(cases),
        "",
        "## Agent Trace Summary",
        "",
        agent_trace_summary(cases),
        "",
        "## Config Snapshot",
        "",
        code_block(run.get("config_snapshot") or {}),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def row(label: str, value: Any) -> str:
    return f"| {escape_table(label)} | {escape_table(format_value(value))} |"


def metrics_table(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "_No metrics recorded._"
    lines = ["| Metric | Value |", "| --- | --- |"]
    for key in sorted(metrics):
        if key == "failure_distribution":
            continue
        lines.append(row(metric_label(key), format_metric(key, metrics[key])))
    return "\n".join(lines)


def failure_table(failures: dict[str, Any]) -> str:
    if not failures:
        return "_No failures recorded._"
    lines = ["| Failure Category | Count |", "| --- | ---: |"]
    for category, count in sorted(failures.items()):
        lines.append(f"| {escape_table(category)} | {escape_table(format_value(count))} |")
    return "\n".join(lines)


def cases_table(cases: list[dict[str, Any]]) -> str:
    if not cases:
        return "_No case artifacts recorded._"
    lines = [
        "| Case | Status | Passed | Latency | Failure | Prompt | Result |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for case in cases:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(case.get("case_id") or case.get("evaluation_id")),
                    escape_table(case.get("status")),
                    escape_table(format_bool(case.get("passed"))),
                    escape_table(format_latency(case.get("latency_ms"))),
                    escape_table(case.get("failure_category") or "-"),
                    escape_table(short_text(case.get("prompt"), 120)),
                    escape_table(result_summary(case)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def agent_trace_summary(cases: list[dict[str, Any]]) -> str:
    traces = [case.get("agent_trace") for case in cases if case.get("agent_trace")]
    if not traces:
        return "_No agent traces recorded for this evaluation run._"

    lines = [
        "| Agent Run | Status | Iterations | Tool Calls | Test | Summary |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for trace in traces:
        steps_by_type = trace.get("steps_by_type") or {}
        test_result = trace.get("test_result") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(trace.get("run_id")),
                    escape_table(trace.get("status")),
                    escape_table(format_value(trace.get("iterations"))),
                    escape_table(format_value(steps_by_type.get("tool_call", 0))),
                    escape_table(test_label(test_result)),
                    escape_table(short_text(trace.get("final_summary") or trace.get("failure_reason"), 120)),
                ]
            )
            + " |"
        )

    lines.extend(["", "### Step Counts", "", "| Agent Run | Step Counts |", "| --- | --- |"])
    for trace in traces:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(trace.get("run_id")),
                    escape_table(join_counts(trace.get("steps_by_type") or {})),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def result_summary(case: dict[str, Any]) -> str:
    result = case.get("result_json")
    if not isinstance(result, dict):
        return short_text(result, 120)
    if case.get("task_type") == "fix":
        parts = [
            f"agent={result.get('agent_status', 'n/a')}",
            f"calls={result.get('tool_calls', 'n/a')}",
            f"diff={result.get('final_diff_length', 'n/a')}",
        ]
        if result.get("error"):
            parts.append(f"error={short_text(result.get('error'), 60)}")
        return ", ".join(parts)

    citations = result.get("citations")
    if isinstance(citations, list) and citations:
        first = citations[0]
        if isinstance(first, dict):
            return f"top={first.get('file_path', 'n/a')}, citations={len(citations)}"
    if result.get("error"):
        return f"error={short_text(result.get('error'), 80)}"
    return "n/a"


def dataset_label(run: dict[str, Any]) -> str:
    dataset_id = run.get("dataset_id")
    version = run.get("dataset_version")
    if not dataset_id:
        return "manual"
    return f"{dataset_id} v{version or 'n/a'}"


def metric_label(key: str) -> str:
    labels = {
        "recall_at_5": "Recall@5",
        "fix_success_rate": "Fix Success Rate",
        "avg_latency_sec": "Avg Latency",
        "avg_tool_calls": "Avg Tool Calls",
        "passed": "Passed",
        "failed": "Failed",
        "cases": "Cases",
        "top_k": "Top K",
    }
    return labels.get(key, key)


def format_metric(key: str, value: Any) -> str:
    if isinstance(value, (int, float)) and key in {"recall_at_5", "fix_success_rate"}:
        return f"{value * 100:.1f}%"
    if isinstance(value, float):
        return f"{value:.4f}"
    return format_value(value)


def format_latency(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value / 1000:.3f}s"


def format_bool(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "n/a"


def format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def test_label(test_result: dict[str, Any]) -> str:
    if not test_result:
        return "n/a"
    if test_result.get("tests_ran"):
        return "passed" if test_result.get("passed") else "failed"
    if test_result.get("skipped_reason"):
        return f"skipped: {test_result.get('skipped_reason')}"
    return "not run"


def join_values(values: Any) -> str:
    if not values:
        return "n/a"
    if isinstance(values, list):
        return ", ".join(str(value) for value in values)
    return str(values)


def join_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "n/a"
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def short_text(value: Any, limit: int) -> str:
    text = format_value(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def escape_table(value: Any) -> str:
    return escape_markdown(format_value(value)).replace("|", "\\|").replace("\n", "<br>")


def escape_markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`")


def code_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


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
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Failed to reach Evaluation API: {exc}", file=sys.stderr)
        sys.exit(1)
