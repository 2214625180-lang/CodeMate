import type { EvaluationSnapshotBackfillResult } from "./types";

export type EvaluationBackfillReport = {
  report_version: string;
  generated_at: string;
  operation: "dataset_snapshot_backfill";
  parameters: {
    dataset_id: string | null;
    dry_run: boolean;
    create_missing_snapshots: boolean;
  };
  result: EvaluationSnapshotBackfillResult;
};

export function buildEvaluationBackfillReport(
  result: EvaluationSnapshotBackfillResult,
  datasetId: string | null
): EvaluationBackfillReport {
  return {
    report_version: "1",
    generated_at: new Date().toISOString(),
    operation: "dataset_snapshot_backfill",
    parameters: {
      dataset_id: datasetId,
      dry_run: result.dry_run,
      create_missing_snapshots: true
    },
    result
  };
}

export function renderEvaluationBackfillReportMarkdown(report: EvaluationBackfillReport) {
  const { result, parameters } = report;
  return `${[
    "# 数据集快照回填报告",
    "",
    "## 摘要",
    "",
    "| 字段 | 值 |",
    "| --- | --- |",
    row("生成时间", report.generated_at),
    row("数据集", parameters.dataset_id ?? "all"),
    row("模式", result.dry_run ? "预演" : "applied"),
    row("创建缺失快照", parameters.create_missing_snapshots),
    row("已扫描运行", result.scanned),
    row("已回填运行", result.backfilled),
    row("已跳过运行", result.skipped),
    row("新建快照", result.created_snapshots),
    "",
    "## 状态统计",
    "",
    statusCountsTable(result.status_counts),
    "",
    "## 详情",
    "",
    detailsTable(result.details)
  ].join("\n").trim()}\n`;
}

export function backfillReportFilename(report: EvaluationBackfillReport, extension: "json" | "md") {
  const datasetId = report.parameters.dataset_id ?? "all-datasets";
  const mode = report.result.dry_run ? "dry-run" : "applied";
  return `${datasetId}-snapshot-backfill-${mode}.${extension}`;
}

function statusCountsTable(counts: Record<string, number>) {
  const entries = Object.entries(counts).sort(([left], [right]) => left.localeCompare(right));
  if (entries.length === 0) {
    return "_暂无状态记录。_";
  }
  return [
    "| 状态 | 数量 |",
    "| --- | ---: |",
    ...entries.map(([status, count]) => `| ${escapeTable(status)} | ${count} |`)
  ].join("\n");
}

function detailsTable(details: Record<string, unknown>[]) {
  if (details.length === 0) {
    return "_暂无逐次运行详情。_";
  }
  return [
    "| 运行 | 状态 | 数据集版本 | 快照 | 是否创建快照 | 原因 |",
    "| --- | --- | ---: | --- | --- | --- |",
    ...details.slice(0, 50).map((item) =>
      [
        escapeTable(item.run_id),
        escapeTable(item.status),
        escapeTable(item.dataset_version),
        escapeTable(item.dataset_snapshot_id ?? item.snapshot_id ?? "n/a"),
        escapeTable(item.created_snapshot_id ?? "n/a"),
        escapeTable(shortText(item.reason, 120))
      ].join(" | ")
    ).map((line) => `| ${line} |`),
    ...(details.length > 50
      ? [`| ... | 已截断 |  |  |  | ${details.length - 50} 条更多详情 |`]
      : [])
  ].join("\n");
}

function row(label: string, value: unknown) {
  return `| ${escapeTable(label)} | ${escapeTable(formatValue(value))} |`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function shortText(value: unknown, limit: number) {
  const text = formatValue(value).replace(/\n/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function escapeTable(value: unknown) {
  return formatValue(value).replace(/\|/g, "\\|").replace(/\n/g, "<br>");
}
