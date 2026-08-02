import type { EvaluationArtifactCase, EvaluationRunArtifact } from "./types";

export function renderEvaluationArtifactMarkdown(artifact: EvaluationRunArtifact): string {
  const { run } = artifact;
  const summary = artifact.summary ?? {};
  const metrics = recordValue(summary.metrics) ?? run.metrics_json ?? {};
  const title = run.name || run.id || "Evaluation Run";

  const lines = [
    `# Evaluation Report: ${escapeMarkdown(title)}`,
    "",
    "## Run Summary",
    "",
    "| Field | Value |",
    "| --- | --- |",
    row("Run ID", run.id),
    row("Task Type", run.task_type),
    row("Status", run.status),
    row("Dataset", datasetLabel(artifact)),
    row("Dataset Snapshot", run.dataset_snapshot_id),
    row("Created At", run.created_at),
    row("Finished At", run.finished_at),
    row("Cases", summary.cases ?? run.case_count),
    row("Passed", summary.passed ?? run.passed_count),
    row("Failed", summary.failed ?? run.failed_count),
    row("Providers", joinValues(summary.providers)),
    row("Models", joinValues(summary.models)),
    "",
    "## Metrics",
    "",
    metricsTable(metrics),
    "",
    "## Failure Distribution",
    "",
    failureTable(recordValue(summary.failure_distribution) ?? recordValue(metrics.failure_distribution) ?? {}),
    "",
    "## Cases",
    "",
    casesTable(artifact.cases),
    "",
    "## Agent Trace Summary",
    "",
    agentTraceSummary(artifact.cases),
    "",
    "## Config Snapshot",
    "",
    codeBlock(run.config_snapshot),
    ""
  ];

  return `${lines.join("\n").trim()}\n`;
}

export function artifactFilename(artifact: EvaluationRunArtifact, extension: "json" | "md") {
  const runId = artifact.run.id || "evaluation-run";
  return `evaluation-${runId}-artifact.${extension}`;
}

function row(label: string, value: unknown) {
  return `| ${escapeTable(label)} | ${escapeTable(formatValue(value))} |`;
}

function metricsTable(metrics: Record<string, unknown>) {
  const keys = Object.keys(metrics).filter((key) => key !== "failure_distribution").sort();
  if (keys.length === 0) {
    return "_No metrics recorded._";
  }

  return [
    "| Metric | Value |",
    "| --- | --- |",
    ...keys.map((key) => row(metricLabel(key), formatMetric(key, metrics[key])))
  ].join("\n");
}

function failureTable(failures: Record<string, unknown>) {
  const entries = Object.entries(failures).sort(([left], [right]) => left.localeCompare(right));
  if (entries.length === 0) {
    return "_No failures recorded._";
  }

  return [
    "| Failure Category | Count |",
    "| --- | ---: |",
    ...entries.map(([category, count]) => `| ${escapeTable(category)} | ${escapeTable(count)} |`)
  ].join("\n");
}

function casesTable(cases: EvaluationArtifactCase[]) {
  if (cases.length === 0) {
    return "_No case artifacts recorded._";
  }

  return [
    "| Case | Status | Passed | Latency | Failure | Prompt | Result |",
    "| --- | --- | --- | ---: | --- | --- | --- |",
    ...cases.map((item) =>
      [
        item.case_id || item.evaluation_id,
        item.status,
        formatBool(item.passed),
        formatLatency(item.latency_ms),
        item.failure_category || "-",
        shortText(item.prompt, 120),
        resultSummary(item)
      ]
        .map(escapeTable)
        .join(" | ")
    )
  ]
    .map((line, index) => (index < 2 ? line : `| ${line} |`))
    .join("\n");
}

function agentTraceSummary(cases: EvaluationArtifactCase[]) {
  const traces = cases.map((item) => item.agent_trace).filter((trace) => trace !== null);
  if (traces.length === 0) {
    return "_No agent traces recorded for this evaluation run._";
  }

  const table = [
    "| Agent Run | Status | Iterations | Tool Calls | Test | Summary |",
    "| --- | --- | ---: | ---: | --- | --- |",
    ...traces.map((trace) =>
      [
        trace.run_id,
        trace.status,
        trace.iterations,
        trace.steps_by_type.tool_call ?? 0,
        testLabel(trace.test_result),
        shortText(trace.final_summary || trace.failure_reason, 120)
      ]
        .map(escapeTable)
        .join(" | ")
    )
  ].map((line, index) => (index < 2 ? line : `| ${line} |`));

  const stepCounts = [
    "",
    "### Step Counts",
    "",
    "| Agent Run | Step Counts |",
    "| --- | --- |",
    ...traces.map((trace) => `| ${escapeTable(trace.run_id)} | ${escapeTable(joinCounts(trace.steps_by_type))} |`)
  ];

  return [...table, ...stepCounts].join("\n");
}

function resultSummary(item: EvaluationArtifactCase) {
  if (!isRecord(item.result_json)) {
    return shortText(item.result_json, 120);
  }

  if (item.task_type === "fix") {
    const parts = [
      `agent=${formatValue(item.result_json.agent_status ?? "n/a")}`,
      `calls=${formatValue(item.result_json.tool_calls ?? "n/a")}`,
      `diff=${formatValue(item.result_json.final_diff_length ?? "n/a")}`
    ];
    if (item.result_json.error) {
      parts.push(`error=${shortText(item.result_json.error, 60)}`);
    }
    return parts.join(", ");
  }

  if (Array.isArray(item.result_json.citations) && item.result_json.citations.length > 0) {
    const first = item.result_json.citations[0];
    if (isRecord(first)) {
      return `top=${formatValue(first.file_path ?? "n/a")}, citations=${item.result_json.citations.length}`;
    }
  }
  if (item.result_json.error) {
    return `error=${shortText(item.result_json.error, 80)}`;
  }
  return "n/a";
}

function datasetLabel(artifact: EvaluationRunArtifact) {
  if (!artifact.run.dataset_id) {
    return "manual";
  }
  return `${artifact.run.dataset_id} v${artifact.run.dataset_version ?? "n/a"}`;
}

function metricLabel(key: string) {
  const labels: Record<string, string> = {
    fix_success_rate: "Fix Success Rate",
    final_verified_fix_rate: "Final Verified Fix Rate",
    avg_latency_sec: "Avg Latency",
    avg_tool_calls: "Avg Tool Calls",
    passed: "Passed",
    failed: "Failed",
    cases: "Cases",
    top_k: "Top K"
  };
  return /^recall_at_\d+$/.test(key) ? `Recall@${key.replace("recall_at_", "")}` : labels[key] ?? key;
}

function formatMetric(key: string, value: unknown) {
  if (
    typeof value === "number" &&
    (/^recall_at_\d+$/.test(key) || key.endsWith("_rate"))
  ) {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (typeof value === "number" && !Number.isInteger(value)) {
    return value.toFixed(4);
  }
  return formatValue(value);
}

function formatLatency(value: unknown) {
  return typeof value === "number" ? `${(value / 1000).toFixed(3)}s` : "n/a";
}

function formatBool(value: unknown) {
  if (value === true) {
    return "yes";
  }
  if (value === false) {
    return "no";
  }
  return "n/a";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "n/a";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function testLabel(testResult: Record<string, unknown> | null) {
  if (!testResult) {
    return "n/a";
  }
  if (typeof testResult.status === "string") {
    return testResult.status;
  }
  if (testResult.tests_ran) {
    return testResult.passed ? "passed" : "failed";
  }
  if (testResult.skipped_reason) {
    return `skipped: ${formatValue(testResult.skipped_reason)}`;
  }
  return "not run";
}

function joinValues(value: unknown) {
  return Array.isArray(value) && value.length > 0 ? value.map(String).join(", ") : "n/a";
}

function joinCounts(counts: Record<string, number>) {
  const entries = Object.entries(counts).sort(([left], [right]) => left.localeCompare(right));
  return entries.length > 0 ? entries.map(([key, value]) => `${key}: ${value}`).join(", ") : "n/a";
}

function shortText(value: unknown, limit: number) {
  const text = formatValue(value).replace(/\n/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function escapeTable(value: unknown) {
  return escapeMarkdown(formatValue(value)).replace(/\|/g, "\\|").replace(/\n/g, "<br>");
}

function escapeMarkdown(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/`/g, "\\`");
}

function codeBlock(value: unknown) {
  return `\`\`\`json\n${JSON.stringify(value ?? {}, null, 2)}\n\`\`\``;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
