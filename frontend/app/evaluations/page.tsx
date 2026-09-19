"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  getEvaluationRun,
  getEvaluationRunArtifact,
  listEvaluationDatasets,
  listEvaluationRuns,
  runFixEvaluation,
  runRetrievalEvaluation
} from "@/lib/api";
import { artifactFilename, renderEvaluationArtifactMarkdown } from "@/lib/evaluationArtifact";
import type {
  EvaluationDataset,
  EvaluationRun,
  FixEvaluationCase,
  RetrievalEvaluationCase
} from "@/lib/types";

const DEFAULT_RETRIEVAL_CASES = `{
  "retrieval": [
    {
      "repo_id": "replace-with-repo-id",
      "question": "add 函数在哪里？",
      "expected_file": "src/math.js"
    }
  ]
}`;

const DEFAULT_FIX_CASES = `{
  "fix": [
    {
      "repo_id": "replace-with-repo-id",
      "issue": "add function test fails: expected 5 but received -1",
      "test_command": "npm test",
      "expected_status": "verified_success",
      "expected_diff_contains": ["return a + b"]
    }
  ]
}`;

export default function EvaluationsPage() {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvaluationRun | null>(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [taskType, setTaskType] = useState<"retrieval" | "fix">("retrieval");
  const [name, setName] = useState("手动检索评测");
  const [topK, setTopK] = useState(5);
  const [requireTestsRan, setRequireTestsRan] = useState(true);
  const [casesJson, setCasesJson] = useState(DEFAULT_RETRIEVAL_CASES);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeRun = selectedRun ?? runs[0] ?? null;
  const activeRunId = activeRun?.id;
  const activeRunStatus = activeRun?.status;
  const availableDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.task_type === taskType),
    [datasets, taskType]
  );
  const selectedDataset =
    availableDatasets.find((dataset) => dataset.id === selectedDatasetId) ?? null;

  const loadRuns = useCallback(async () => {
    try {
      const data = await listEvaluationRuns();
      setRuns(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载评测记录失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const loadDatasets = useCallback(async () => {
    try {
      const data = await listEvaluationDatasets();
      setDatasets(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载基准数据集失败");
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    if (!activeRunId || activeRunStatus !== "running") {
      return;
    }

    const interval = window.setInterval(() => {
      void refreshRun(activeRunId);
    }, 1500);
    return () => window.clearInterval(interval);
  }, [activeRunId, activeRunStatus]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsRunning(true);
    setError(null);
    try {
      const run =
        taskType === "retrieval"
          ? await runRetrievalEvaluation({
              name: name.trim() || null,
              dataset_id: selectedDataset?.id ?? null,
              dataset_version: selectedDataset?.version ?? null,
              top_k: topK,
              cases: parseRetrievalCases(casesJson)
            })
          : await runFixEvaluation({
              name: name.trim() || null,
              dataset_id: selectedDataset?.id ?? null,
              dataset_version: selectedDataset?.version ?? null,
              require_tests_ran: requireTestsRan,
              cases: parseFixCases(casesJson)
            });

      setSelectedRun(run);
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      if (run.status === "running") {
        window.setTimeout(() => {
          void refreshRun(run.id);
        }, 800);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "执行评测失败");
    } finally {
      setIsRunning(false);
    }
  }

  function switchTaskType(nextTaskType: "retrieval" | "fix") {
    setTaskType(nextTaskType);
    setSelectedDatasetId("");
    setName(nextTaskType === "retrieval" ? "手动检索评测" : "手动修复评测");
    setCasesJson(nextTaskType === "retrieval" ? DEFAULT_RETRIEVAL_CASES : DEFAULT_FIX_CASES);
  }

  function applyDataset(datasetId: string) {
    setSelectedDatasetId(datasetId);
    const dataset = availableDatasets.find((item) => item.id === datasetId);
    if (!dataset) {
      return;
    }
    setName(`${dataset.name} 评测`);
    setCasesJson(JSON.stringify({ [dataset.task_type]: dataset.cases_json }, null, 2));
  }

  async function refreshRun(evaluationRunId: string) {
    try {
      const run = await getEvaluationRun(evaluationRunId);
      setSelectedRun((current) => (current?.id === run.id ? run : current));
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新评测运行失败");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">P2</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">评测中心</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            执行检索与代码修复评测，保存指标并查看各用例的失败情况。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/evaluations/history"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            历史记录
          </Link>
          <Link
            href="/evaluations/compare"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            回归报告
          </Link>
          <Link
            href="/evaluations/datasets"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            基准数据集
          </Link>
        </div>
      </div>

      <section className="grid gap-6 lg:grid-cols-[minmax(0,0.95fr)_minmax(420px,1.05fr)]">
        <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
          <div className="mb-4 inline-flex rounded-md border border-border bg-white p-1">
            {(["retrieval", "fix"] as const).map((nextTaskType) => (
              <button
                key={nextTaskType}
                type="button"
                onClick={() => switchTaskType(nextTaskType)}
                className={`rounded px-3 py-1.5 text-sm font-medium ${
                  taskType === nextTaskType
                    ? "bg-slate-950 text-white"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {nextTaskType === "retrieval" ? "检索" : "代码修复"}
              </button>
            ))}
          </div>

          <div className="mb-4 rounded-md border border-border bg-slate-50 p-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[220px] flex-1">
                <label htmlFor="benchmark-dataset" className="text-sm font-medium text-slate-700">
                  基准数据集
                </label>
                <select
                  id="benchmark-dataset"
                  value={selectedDatasetId}
                  onChange={(event) => applyDataset(event.target.value)}
                  className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500"
                >
                  <option value="">手动输入用例</option>
                  {availableDatasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name} v{dataset.version} ({dataset.cases_json.length})
                    </option>
                  ))}
                </select>
              </div>
              <Link
                href="/evaluations/datasets"
                className="rounded-md border border-border bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                管理
              </Link>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_140px]">
            <div>
              <label htmlFor="eval-name" className="text-sm font-medium text-slate-700">
                运行名称
              </label>
              <input
                id="eval-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
              />
            </div>

            {taskType === "retrieval" ? (
              <div>
                <label htmlFor="top-k" className="text-sm font-medium text-slate-700">
                  Top K
                </label>
                <input
                  id="top-k"
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                  className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
                />
              </div>
            ) : (
              <label className="flex items-end gap-2 pb-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={requireTestsRan}
                  onChange={(event) => setRequireTestsRan(event.target.checked)}
                  className="h-4 w-4 rounded border-border"
                />
                要求执行测试
              </label>
            )}
          </div>

          <label htmlFor="cases-json" className="mt-4 block text-sm font-medium text-slate-700">
            {taskType === "retrieval" ? "检索用例 JSON" : "修复用例 JSON"}
          </label>
          <textarea
            id="cases-json"
            value={casesJson}
            onChange={(event) => setCasesJson(event.target.value)}
            className="mt-2 min-h-[420px] w-full resize-y rounded-md border border-border px-3 py-2 font-mono text-xs outline-none focus:border-slate-500"
            spellCheck={false}
          />

          <div className="mt-4 flex justify-end">
            <button
              type="submit"
              disabled={isRunning}
              className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isRunning
                ? "正在运行…"
                : taskType === "retrieval"
                  ? "运行检索评测"
                  : "运行修复评测"}
            </button>
          </div>
        </form>

        <div className="space-y-6">
          {error ? (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
          ) : null}

          <RunSummary run={activeRun} isLoading={isLoading} />
          <RecentRuns runs={runs} activeRun={activeRun} onSelect={setSelectedRun} />
        </div>
      </section>

      <RunDetails run={activeRun} />
    </div>
  );
}

function RecentRuns({
  runs,
  activeRun,
  onSelect
}: {
  runs: EvaluationRun[];
  activeRun: EvaluationRun | null;
  onSelect: (run: EvaluationRun) => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">最近运行</h2>
      {runs.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">暂无评测记录。</p>
      ) : (
        <div className="mt-4 space-y-2">
          {runs.map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => onSelect(run)}
              className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                activeRun?.id === run.id
                  ? "border-slate-400 bg-slate-50"
                  : "border-border bg-white hover:bg-slate-50"
              }`}
            >
              <span className="block font-medium text-slate-950">{run.name || run.id}</span>
              <span className="mt-1 block text-xs text-slate-500">
                {run.task_type} · {run.status}
                {run.dataset_version ? ` · 数据集 v${run.dataset_version}` : ""} ·{" "}
                {new Date(run.created_at).toLocaleString()}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function RunSummary({ run, isLoading }: { run: EvaluationRun | null; isLoading: boolean }) {
  if (isLoading) {
    return (
      <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
        正在加载评测记录…
      </section>
    );
  }
  if (!run) {
    return (
      <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
        运行评测后可查看指标。
      </section>
    );
  }

  const metrics = run.metrics_json;
  const primaryMetricName =
    stringValue(metrics.primary_metric) ??
    (run.task_type === "fix"
      ? "final_verified_fix_rate"
      : `recall_at_${numberMetric(metrics, "top_k") ?? 5}`);
  const primaryMetric = numberMetric(metrics, primaryMetricName);
  const avgLatency = numberMetric(metrics, "avg_latency_sec");
  const avgToolCalls = numberMetric(metrics, "avg_tool_calls");
  const failures = recordMetric(metrics, "failure_distribution");

  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{run.name || run.id}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {run.task_type} · {run.status} ·{" "}
            {run.finished_at ? new Date(run.finished_at).toLocaleString() : "running"}
            {run.dataset_version ? ` · 数据集 v${run.dataset_version}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
            {run.status === "running"
              ? `${run.results.length}/${run.case_count} 个用例已记录`
              : `${run.passed_count}/${run.case_count} 个通过`}
          </span>
          <ArtifactActions run={run} />
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Metric
          label={metricLabel(primaryMetricName)}
          value={
            run.status === "running"
              ? "running"
              : primaryMetric === null
                ? "n/a"
                : `${Math.round(primaryMetric * 100)}%`
          }
        />
        <Metric
          label={run.task_type === "fix" ? "平均工具调用次数" : "平均耗时"}
          value={
            run.task_type === "fix"
              ? avgToolCalls === null
                ? "n/a"
                : avgToolCalls.toFixed(1)
              : avgLatency === null
                ? "n/a"
                : `${avgLatency.toFixed(3)}s`
          }
        />
        <Metric label="失败" value={String(run.failed_count)} />
      </div>

      {run.task_type === "fix" ? (
        <div className="mt-3">
          <Metric
            label="平均耗时"
            value={avgLatency === null ? "n/a" : `${avgLatency.toFixed(3)}s`}
          />
        </div>
      ) : null}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <JsonPanel title="失败分布" value={failures} />
        <JsonPanel title="配置快照" value={run.config_snapshot} />
      </div>
    </section>
  );
}

function ArtifactActions({ run }: { run: EvaluationRun }) {
  const [isExporting, setIsExporting] = useState<"json" | "markdown" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function exportArtifact(format: "json" | "markdown") {
    setIsExporting(format);
    setError(null);
    try {
      const artifact = await getEvaluationRunArtifact(run.id);
      const content =
        format === "json"
          ? `${JSON.stringify(artifact, null, 2)}\n`
          : renderEvaluationArtifactMarkdown(artifact);
      downloadText(
        content,
        artifactFilename(artifact, format === "json" ? "json" : "md"),
        format === "json" ? "application/json" : "text/markdown"
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出产物失败");
    } finally {
      setIsExporting(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <Link
        href={`/evaluations/artifact?runId=${encodeURIComponent(run.id)}`}
        className="rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
      >
        预览
      </Link>
      <button
        type="button"
        disabled={isExporting !== null}
        onClick={() => void exportArtifact("json")}
        className="rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
      >
        {isExporting === "json" ? "正在导出…" : "导出 JSON"}
      </button>
      <button
        type="button"
        disabled={isExporting !== null}
        onClick={() => void exportArtifact("markdown")}
        className="rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
      >
        {isExporting === "markdown" ? "正在导出…" : "导出 Markdown"}
      </button>
      {error ? <span className="basis-full text-right text-xs text-red-600">{error}</span> : null}
    </div>
  );
}

function RunDetails({ run }: { run: EvaluationRun | null }) {
  const rows = useMemo(() => run?.results ?? [], [run]);
  if (!run) {
    return null;
  }

  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">用例结果</h2>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">暂无用例结果。</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase text-slate-500">
                <th className="py-2 pr-3 font-medium">用例</th>
                <th className="py-2 pr-3 font-medium">预期</th>
                <th className="py-2 pr-3 font-medium">状态</th>
                <th className="py-2 pr-3 font-medium">耗时</th>
                <th className="py-2 pr-3 font-medium">结果</th>
                <th className="py-2 font-medium">失败原因</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((result) => (
                <tr key={result.id} className="border-b border-border align-top">
                  <td className="py-3 pr-3">
                    <p className="font-medium text-slate-950">{result.case_id ?? result.id}</p>
                    <p className="mt-1 max-w-xs truncate text-xs text-slate-500">
                      {result.question}
                    </p>
                  </td>
                  <td className="py-3 pr-3 font-mono text-xs text-slate-700">
                    {expectedValue(result)}
                  </td>
                  <td className="py-3 pr-3">
                    <span
                      className={`rounded-full px-2 py-1 text-xs font-medium ${
                        result.passed
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {result.status ?? "unknown"}
                    </span>
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-600">
                    {result.latency_ms === null ? "n/a" : `${result.latency_ms}ms`}
                  </td>
                  <td className="py-3 pr-3 font-mono text-xs text-slate-700">
                    {resultValue(result)}
                  </td>
                  <td className="py-3 text-xs text-slate-600">
                    {result.failure_category ?? "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <pre className="mt-2 max-h-60 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
        <code>{JSON.stringify(value ?? {}, null, 2)}</code>
      </pre>
    </div>
  );
}

function downloadText(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function parseRetrievalCases(raw: string): RetrievalEvaluationCase[] {
  const parsed = JSON.parse(raw) as unknown;
  const cases = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed) && Array.isArray(parsed.retrieval)
      ? parsed.retrieval
      : null;

  if (!cases || cases.length === 0) {
    throw new Error("JSON 必须是检索用例数组，或包含 retrieval[] 的对象。");
  }

  return cases.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`用例 ${index + 1} 必须是对象。`);
    }
    const repoId = stringValue(item.repo_id);
    const question = stringValue(item.question);
    const expectedFile = stringValue(item.expected_file);
    if (!repoId || !question || !expectedFile) {
      throw new Error(`用例 ${index + 1} 必须包含 repo_id、question 和 expected_file。`);
    }
    return {
      case_id: stringValue(item.case_id),
      repo_id: repoId,
      question,
      expected_file: expectedFile,
      expected_lines:
        Array.isArray(item.expected_lines) || isRecord(item.expected_lines)
          ? item.expected_lines
          : null
    };
  });
}

function parseFixCases(raw: string): FixEvaluationCase[] {
  const parsed = JSON.parse(raw) as unknown;
  const cases = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed) && Array.isArray(parsed.fix)
      ? parsed.fix
      : null;

  if (!cases || cases.length === 0) {
    throw new Error("JSON 必须是修复用例数组，或包含 fix[] 的对象。");
  }

  return cases.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`用例 ${index + 1} 必须是对象。`);
    }
    const repoId = stringValue(item.repo_id);
    const issue = stringValue(item.issue);
    const rawExpectedStatus = stringValue(item.expected_status);
    const expectedStatus = rawExpectedStatus === "success"
      ? "verified_success"
      : rawExpectedStatus ?? "verified_success";
    if (!repoId || !issue) {
      throw new Error(`用例 ${index + 1} 必须包含 repo_id 和 issue。`);
    }
    if (!isFixExpectedStatus(expectedStatus)) {
      throw new Error(
        `用例 ${index + 1} 的 expected_status 必须是严格验证状态。`
      );
    }
    return {
      case_id: stringValue(item.case_id),
      repo_id: repoId,
      issue,
      test_command: stringValue(item.test_command),
      expected_status: expectedStatus,
      expected_diff_contains: Array.isArray(item.expected_diff_contains)
        ? item.expected_diff_contains.filter((value): value is string => typeof value === "string")
        : []
    };
  });
}

function expectedValue(result: {
  task_type: string;
  expected_file: string | null;
  metadata_json: Record<string, unknown>;
}) {
  if (result.task_type === "fix") {
    return stringValue(result.metadata_json.expected_status) ?? "verified_success";
  }
  return result.expected_file ?? "n/a";
}

function resultValue(result: {
  task_type: string;
  result_json: Record<string, unknown> | unknown[] | null;
}) {
  if (result.task_type === "fix") {
    if (!isRecord(result.result_json)) {
      return "n/a";
    }
    const status = stringValue(result.result_json.agent_status) ?? "unknown";
    const calls =
      typeof result.result_json.tool_calls === "number"
        ? `${result.result_json.tool_calls} 次调用`
        : "n/a";
    return `${status} · ${calls}`;
  }
  return topCitationPath(result.result_json);
}

function numberMetric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return typeof value === "number" ? value : null;
}

function metricLabel(name: string) {
  if (/^recall_at_\d+$/.test(name)) {
    return `Recall@${name.replace("recall_at_", "")}`;
  }
  const labels: Record<string, string> = {
    final_verified_fix_rate: "最终验证通过率",
    fix_success_rate: "修复成功率"
  };
  return labels[name] ?? name;
}

function recordMetric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return isRecord(value) ? value : {};
}

function topCitationPath(resultJson: Record<string, unknown> | unknown[] | null) {
  if (!isRecord(resultJson) || !Array.isArray(resultJson.citations)) {
    return "n/a";
  }
  const first = resultJson.citations[0];
  if (!isRecord(first)) {
    return "n/a";
  }
  return stringValue(first.file_path) || "n/a";
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isFixExpectedStatus(
  value: string
): value is NonNullable<FixEvaluationCase["expected_status"]> {
  return [
    "verified_success",
    "unverified_patch",
    "not_reproduced",
    "failed",
    "infra_error"
  ].some((status) => status === value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
