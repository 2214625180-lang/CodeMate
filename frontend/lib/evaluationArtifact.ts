import type { EvaluationArtifactCase, EvaluationRunArtifact } from "./types";

export function renderEvaluationArtifactMarkdown(artifact: EvaluationRunArtifact): string {
  const { run } = artifact;
  const summary = artifact.summary ?? {};
  const metrics = recordValue(summary.metrics) ?? run.metrics_json ?? {};
  const title = run.name || run.id || "评测运行";

  const lines = [
    `# 评测报告：${escapeMarkdown(title)}`,
    "",
    "## 运行摘要",
    "",
    "| 字段 | 值 |",
    "| --- | --- |",
    row("运行 ID", run.id),
    row("任务类型", run.task_type),
    row("状态", run.status),
    row("数据集", datasetLabel(artifact)),
    row("数据集快照", run.dataset_snapshot_id),
    row("创建时间", run.created_at),
    row("完成时间", run.finished_at),
    row("用例", summary.cases ?? run.case_count),
    row("通过", summary.passed ?? run.passed_count),
    row("失败", summary.failed ?? run.failed_count),
    row("服务商", joinValues(summary.providers)),
    row("模型", joinValues(summary.models)),
    "",
    "## 指标",
    "",
    metricsTable(metrics),
    "",
    "## 失败分布",
    "",
    failureTable(recordValue(summary.failure_distribution) ?? recordValue(metrics.failure_distribution) ?? {}),
    "",
    "## 用例",
    "",
    casesTable(artifact.cases),
    "",
    "## Agent 执行轨迹摘要",
    "",
    agentTraceSummary(artifact.cases),
    "",
    "## 配置快照",
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
    return "_暂无指标记录。_";
  }

  return [
    "| 指标 | 值 |",
    "| --- | --- |",
    ...keys.map((key) => row(metricLabel(key), formatMetric(key, metrics[key])))
  ].join("\n");
}

function failureTable(failures: Record<string, unknown>) {
  const entries = Object.entries(failures).sort(([left], [right]) => left.localeCompare(right));
  if (entries.length === 0) {
    return "_暂无失败记录。_";
  }

  return [
    "| 失败类别 | 数量 |",
    "| --- | ---: |",
    ...entries.map(([category, count]) => `| ${escapeTable(category)} | ${escapeTable(count)} |`)
  ].join("\n");
}

function casesTable(cases: EvaluationArtifactCase[]) {
  if (cases.length === 0) {
    return "_暂无用例产物。_";
  }

  return [
    "| 用例 | 状态 | 是否通过 | 耗时 | 失败原因 | 提示词 | 结果 |",
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
    return "_本次评测暂无 Agent 执行轨迹。_";
  }

  const table = [
    "| Agent 运行 | 状态 | 迭代次数 | 工具调用次数 | 测试 | 摘要 |",
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
    "### 步骤统计",
    "",
    "| Agent 运行 | 步骤统计 |",
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
      `Agent=${formatValue(item.result_json.agent_status ?? "n/a")}`,
      `调用次数=${formatValue(item.result_json.tool_calls ?? "n/a")}`,
      `Diff=${formatValue(item.result_json.final_diff_length ?? "n/a")}`
    ];
    if (item.result_json.error) {
      parts.push(`错误=${shortText(item.result_json.error, 60)}`);
    }
    return parts.join(", ");
  }

  if (Array.isArray(item.result_json.citations) && item.result_json.citations.length > 0) {
    const first = item.result_json.citations[0];
    if (isRecord(first)) {
      return `首个结果=${formatValue(first.file_path ?? "n/a")}，引用数=${item.result_json.citations.length}`;
    }
  }
  if (item.result_json.error) {
    return `错误=${shortText(item.result_json.error, 80)}`;
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
    fix_success_rate: "修复成功率",
    final_verified_fix_rate: "最终验证通过率",
    avg_latency_sec: "平均耗时",
    avg_tool_calls: "平均工具调用次数",
    passed: "通过",
    failed: "失败",
    cases: "用例",
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
    return `已跳过：${formatValue(testResult.skipped_reason)}`;
  }
  return "未运行";
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
