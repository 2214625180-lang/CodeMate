import os
from pathlib import Path
from typing import Any


def write_gate_summary(
    *,
    gate_result: dict[str, Any],
    artifact_paths: dict[str, str],
    output_path: str | None,
    append_github_step_summary: bool,
    candidate_run_status: str | None = None,
) -> dict[str, str]:
    markdown = render_gate_summary(
        gate_result,
        artifact_paths=artifact_paths,
        candidate_run_status=candidate_run_status,
    )
    return write_summary_markdown(
        markdown=markdown,
        output_path=output_path,
        append_github_step_summary=append_github_step_summary,
    )


def write_timeout_summary(
    *,
    dataset_id: str,
    candidate_run_id: str,
    candidate_run_status: str | None,
    artifact_paths: dict[str, str],
    output_path: str | None,
    append_github_step_summary: bool,
) -> dict[str, str]:
    markdown = render_timeout_summary(
        dataset_id=dataset_id,
        candidate_run_id=candidate_run_id,
        candidate_run_status=candidate_run_status,
        artifact_paths=artifact_paths,
    )
    return write_summary_markdown(
        markdown=markdown,
        output_path=output_path,
        append_github_step_summary=append_github_step_summary,
    )


def write_summary_markdown(
    *,
    markdown: str,
    output_path: str | None,
    append_github_step_summary: bool,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        paths["markdown"] = str(path)

    github_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if append_github_step_summary and github_summary_path:
        path = Path(github_summary_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(markdown)
            if not markdown.endswith("\n"):
                handle.write("\n")
        paths["github_step_summary"] = str(path)
    return paths


def default_summary_output_path(*, artifact_dir: str, candidate_run_id: str) -> str:
    return str(Path(artifact_dir) / f"{candidate_run_id}-gate-summary.md")


def render_gate_summary(
    gate_result: dict[str, Any],
    *,
    artifact_paths: dict[str, str],
    candidate_run_status: str | None = None,
) -> str:
    comparison = gate_result.get("comparison") or {}
    summary = comparison.get("summary") or {}
    dataset = gate_result.get("dataset") or {}
    baseline_run = gate_result.get("baseline_run") or {}
    candidate_run = gate_result.get("candidate_run") or {}
    candidate_status = candidate_run_status or candidate_run.get("status")
    status = str(gate_result.get("status") or "unknown")
    primary_metric = comparison.get("primary_metric")
    primary_delta = summary.get("primary_metric_delta") or {}

    lines = [
        f"# CodeMate Evaluation Gate: {status.upper()}",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        row("Gate Status", status.upper()),
        row("Dataset", dataset_label(dataset)),
        row("Baseline Run", baseline_run.get("id")),
        row("Candidate Run", candidate_run.get("id")),
        row("Baseline Snapshot", baseline_run.get("dataset_snapshot_id")),
        row("Candidate Snapshot", candidate_run.get("dataset_snapshot_id")),
        row("Candidate Status", candidate_status),
        row("Task Type", candidate_run.get("task_type") or baseline_run.get("task_type")),
        row("Primary Metric", primary_metric),
        row("Primary Metric Delta", format_delta(primary_delta.get("delta"))),
        row("Regressions", summary.get("regressions")),
        row("Improvements", summary.get("improvements")),
        "",
        "## Metric Deltas",
        "",
        metric_deltas_table(comparison.get("metric_deltas") or []),
        "",
        "## Gate Checks",
        "",
        checks_table(gate_result.get("checks") or []),
        "",
        "## Failed And Regressed Cases",
        "",
        failed_cases_table(comparison.get("case_comparisons") or []),
        "",
        "## Artifacts",
        "",
        artifact_table(artifact_paths),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_timeout_summary(
    *,
    dataset_id: str,
    candidate_run_id: str,
    candidate_run_status: str | None,
    artifact_paths: dict[str, str],
) -> str:
    lines = [
        "# CodeMate Evaluation Gate: TIMEOUT",
        "",
        "The candidate evaluation run did not reach a terminal status before the CI timeout.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        row("Dataset", dataset_id),
        row("Candidate Run", candidate_run_id),
        row("Candidate Status", candidate_run_status),
        "",
        "## Artifacts",
        "",
        artifact_table(artifact_paths),
    ]
    return "\n".join(lines).rstrip() + "\n"


def metric_deltas_table(metric_deltas: list[dict[str, Any]]) -> str:
    if not metric_deltas:
        return "_No metric deltas recorded._"
    lines = [
        "| Metric | Baseline | Candidate | Delta | Percent Delta | Direction |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for metric in metric_deltas:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(metric_label(metric.get("name"))),
                    escape_table(format_number(metric.get("baseline"))),
                    escape_table(format_number(metric.get("candidate"))),
                    escape_table(format_delta(metric.get("delta"))),
                    escape_table(format_percent(metric.get("percent_delta"))),
                    escape_table(metric.get("direction")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def checks_table(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "_No gate checks recorded._"
    lines = [
        "| Check | Result | Observed | Threshold | Message |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(check.get("name")),
                    escape_table(format_check_result(check.get("passed"))),
                    escape_table(short_text(check.get("observed"), 120)),
                    escape_table(short_text(check.get("threshold"), 80)),
                    escape_table(short_text(check.get("message"), 160)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def failed_cases_table(case_comparisons: list[dict[str, Any]]) -> str:
    cases = [
        case
        for case in case_comparisons
        if case.get("status") == "regressed" or case.get("candidate_passed") is False
    ]
    if not cases:
        return "_No failed or regressed candidate cases._"

    lines = [
        "| Case | Status | Baseline | Candidate | Failure | Latency Delta | Prompt |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for case in cases[:20]:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(case.get("case_id")),
                    escape_table(case.get("status")),
                    escape_table(format_bool(case.get("baseline_passed"))),
                    escape_table(format_bool(case.get("candidate_passed"))),
                    escape_table(case.get("candidate_failure_category") or "-"),
                    escape_table(format_latency_delta(case.get("latency_delta_ms"))),
                    escape_table(short_text(case.get("question"), 140)),
                ]
            )
            + " |"
        )
    if len(cases) > 20:
        lines.append(f"| ... | {len(cases) - 20} more cases | | | | | |")
    return "\n".join(lines)


def artifact_table(artifact_paths: dict[str, str]) -> str:
    if not artifact_paths:
        return "_No artifacts exported._"
    lines = ["| Artifact | Path |", "| --- | --- |"]
    for label, path in sorted(artifact_paths.items()):
        lines.append(f"| {escape_table(label)} | `{escape_backticks(path)}` |")
    return "\n".join(lines)


def row(label: str, value: Any) -> str:
    return f"| {escape_table(label)} | {escape_table(format_value(value))} |"


def dataset_label(dataset: dict[str, Any]) -> str:
    dataset_id = dataset.get("id")
    name = dataset.get("name")
    if dataset_id and name:
        return f"{name} ({dataset_id})"
    return name or dataset_id or "n/a"


def metric_label(name: Any) -> str:
    labels = {
        "fix_success_rate": "Fix Success Rate",
        "final_verified_fix_rate": "Final Verified Fix Rate",
        "passed": "Passed",
        "failed": "Failed",
        "avg_latency_sec": "Avg Latency",
        "avg_tool_calls": "Avg Tool Calls",
    }
    normalized = str(name)
    if normalized.startswith("recall_at_") and normalized.removeprefix("recall_at_").isdigit():
        return f"Recall@{normalized.removeprefix('recall_at_')}"
    return labels.get(normalized, str(name or "n/a"))


def format_check_result(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "INCONCLUSIVE"


def format_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "n/a"


def format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format_number(value)
    return str(value)


def format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def format_delta(value: Any) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, int | float):
        return str(value)
    prefix = "+" if value > 0 else ""
    return f"{prefix}{format_number(value)}"


def format_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, int | float):
        return str(value)
    return f"{value * 100:+.2f}%"


def format_latency_delta(value: Any) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, int | float):
        return str(value)
    return f"{value:+.0f} ms"


def short_text(value: Any, limit: int) -> str:
    text = format_value(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def escape_table(value: Any) -> str:
    return escape_backticks(format_value(value)).replace("|", "\\|").replace("\n", " ")


def escape_backticks(value: Any) -> str:
    return format_value(value).replace("`", "\\`")
