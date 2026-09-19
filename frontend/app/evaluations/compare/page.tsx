"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  compareEvaluationRuns,
  evaluateRegressionGate,
  listEvaluationDatasets,
  listEvaluationRuns
} from "@/lib/api";
import type {
  EvaluationCaseComparison,
  EvaluationDataset,
  EvaluationGateResult,
  EvaluationMetricDelta,
  EvaluationRun,
  EvaluationRunCompare
} from "@/lib/types";

export default function EvaluationComparePage() {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [baselineRunId, setBaselineRunId] = useState("");
  const [candidateRunId, setCandidateRunId] = useState("");
  const [report, setReport] = useState<EvaluationRunCompare | null>(null);
  const [gateResult, setGateResult] = useState<EvaluationGateResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isComparing, setIsComparing] = useState(false);
  const [isCheckingGate, setIsCheckingGate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completedRuns = useMemo(
    () => runs.filter((run) => run.status === "completed"),
    [runs]
  );
  const baselineRun = runs.find((run) => run.id === baselineRunId) ?? null;
  const candidateRun = runs.find((run) => run.id === candidateRunId) ?? null;
  const candidateDataset =
    datasets.find((dataset) => dataset.id === candidateRun?.dataset_id) ?? null;

  const loadRuns = useCallback(async () => {
    try {
      const data = await listEvaluationRuns(100);
      setRuns(data);
      const defaults = defaultRunPair(data);
      setBaselineRunId((current) => current || defaults.baselineRunId);
      setCandidateRunId((current) => current || defaults.candidateRunId);
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!baselineRunId || !candidateRunId || baselineRunId === candidateRunId) {
      setError("请选择两次不同的评测运行。");
      return;
    }

    setIsComparing(true);
    setError(null);
    try {
      const data = await compareEvaluationRuns(baselineRunId, candidateRunId);
      setReport(data);
      setGateResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "对比评测运行失败");
    } finally {
      setIsComparing(false);
    }
  }

  async function handleGateCheck() {
    if (!candidateRun || !candidateDataset) {
      setError("请选择属于基准数据集的候选运行。");
      return;
    }

    setIsCheckingGate(true);
    setError(null);
    try {
      const data = await evaluateRegressionGate(candidateDataset.id, candidateRun.id);
      setGateResult(data);
      setReport(data.comparison);
      setBaselineRunId(data.baseline_run.id);
      setCandidateRunId(data.candidate_run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "执行回归门禁检查失败");
    } finally {
      setIsCheckingGate(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">评测中心</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">回归报告</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            对比两次已完成的基准评测，检查指标退化、失败变化和各用例的行为差异。
          </p>
        </div>
        <Link
          href="/evaluations"
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          评测中心
        </Link>
      </div>

      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <RunSelect
            id="baseline-run"
            label="基线"
            value={baselineRunId}
            runs={completedRuns}
            onChange={setBaselineRunId}
          />
          <RunSelect
            id="candidate-run"
            label="候选"
            value={candidateRunId}
            runs={completedRuns}
            onChange={setCandidateRunId}
          />
          <div className="flex items-end">
            <button
              type="submit"
              disabled={isComparing || !baselineRunId || !candidateRunId}
              className="min-h-10 rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isComparing ? "正在对比…" : "生成报告"}
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <RunContext run={baselineRun} title="基线上下文" />
          <RunContext run={candidateRun} title="候选上下文" />
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <div className="text-sm text-slate-600">
            {candidateDataset ? (
              <span>
                门禁策略： {candidateDataset.name} · 基线{" "}
                {candidateDataset.baseline_run_id
                  ? candidateDataset.baseline_run_id.slice(0, 8)
                  : "未设置"}
              </span>
            ) : (
              <span>门禁策略要求候选运行来自基准数据集。</span>
            )}
          </div>
          <button
            type="button"
            disabled={
              isCheckingGate ||
              !candidateRun ||
              !candidateDataset ||
              !candidateDataset.baseline_run_id
            }
            onClick={() => void handleGateCheck()}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
          >
            {isCheckingGate ? "正在检查门禁…" : "检查门禁"}
          </button>
        </div>
      </form>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      {isLoading ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          正在加载评测记录…
        </section>
      ) : completedRuns.length < 2 ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          至少需要两次已完成的评测运行。
        </section>
      ) : null}

      {gateResult ? <GateResultPanel result={gateResult} /> : null}
      {report ? <ReportView report={report} /> : null}
    </div>
  );
}

function RunSelect({
  id,
  label,
  value,
  runs,
  onChange
}: {
  id: string;
  label: string;
  value: string;
  runs: EvaluationRun[];
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500"
      >
        <option value="">选择运行</option>
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {runLabel(run)}
          </option>
        ))}
      </select>
    </div>
  );
}

function RunContext({ run, title }: { run: EvaluationRun | null; title: string }) {
  if (!run) {
    return (
      <div className="rounded-md border border-border bg-slate-50 p-3 text-sm text-slate-500">
        {title}：尚未选择
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-slate-50 p-3">
      <p className="text-sm font-semibold text-slate-950">{title}</p>
      <div className="mt-2 grid gap-1 text-xs text-slate-600">
        <span>{run.name || run.id}</span>
        <span>
          {run.task_type} · 数据集 {run.dataset_id ? run.dataset_id.slice(0, 8) : "manual"} · v
          {run.dataset_version ?? "n/a"}
        </span>
        <span>{modelLabel(run)}</span>
        <span>{new Date(run.created_at).toLocaleString()}</span>
      </div>
    </div>
  );
}

function GateResultPanel({ result }: { result: EvaluationGateResult }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">回归门禁</h2>
          <p className="mt-1 text-sm text-slate-600">
            {result.dataset.name} · 基线 {result.baseline_run.name || result.baseline_run.id}
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${gateStatusClass(
            result.status
          )}`}
        >
          {result.status}
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard
          label="允许的指标降幅"
          value={`${Math.round(result.policy.max_primary_metric_drop * 1000) / 10}%`}
          tone="neutral"
        />
        <MetricCard
          label="最多退化用例数"
          value={String(result.policy.max_regressed_cases)}
          tone="neutral"
        />
        <MetricCard
          label="不兼容"
          value={result.policy.allow_incompatible ? "allowed" : "blocked"}
          tone="neutral"
        />
        <MetricCard
          label="快照"
          value={result.policy.require_matching_dataset_snapshot ? "required" : "ignored"}
          tone="neutral"
        />
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-slate-500">
              <th className="py-2 pr-3 font-medium">检查项</th>
              <th className="py-2 pr-3 font-medium">状态</th>
              <th className="py-2 pr-3 font-medium">实际值</th>
              <th className="py-2 pr-3 font-medium">阈值</th>
              <th className="py-2 font-medium">规则</th>
            </tr>
          </thead>
          <tbody>
            {result.checks.map((check) => (
              <tr key={check.name} className="border-b border-border align-top">
                <td className="py-3 pr-3 font-medium text-slate-950">{checkLabel(check.name)}</td>
                <td className="py-3 pr-3">
                  <span
                    className={`rounded-full px-2 py-1 text-xs font-medium ${checkStatusClass(
                      check.passed
                    )}`}
                  >
                    {check.passed === null ? "unknown" : check.passed ? "passed" : "failed"}
                  </span>
                </td>
                <td className="py-3 pr-3 text-xs text-slate-700">
                  {formatCheckValue(check.observed)}
                </td>
                <td className="py-3 pr-3 text-xs text-slate-700">
                  {formatCheckValue(check.threshold)}
                </td>
                <td className="py-3 text-xs text-slate-600">{check.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ReportView({ report }: { report: EvaluationRunCompare }) {
  const primaryDelta =
    report.metric_deltas.find((metric) => metric.name === report.primary_metric) ?? null;
  const regressions = report.case_comparisons.filter((item) => item.status === "regressed");
  const improvements = report.case_comparisons.filter((item) => item.status === "improved");

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-border bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">报告摘要</h2>
            <p className="mt-1 text-sm text-slate-600">
              {report.baseline_run.name || report.baseline_run.id} →{" "}
              {report.candidate_run.name || report.candidate_run.id}
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${verdictClass(
              report.verdict
            )}`}
          >
            {report.verdict}
          </span>
        </div>

        {report.compatibility_warnings.length > 0 ? (
          <div className="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
            {report.compatibility_warnings.join(" · ")}
          </div>
        ) : null}

        <div className="mt-5 grid gap-3 sm:grid-cols-4">
          <MetricCard
            label={metricLabel(report.primary_metric)}
            value={primaryDelta ? deltaLabel(primaryDelta) : "n/a"}
            tone={primaryDelta ? metricTone(primaryDelta) : "neutral"}
          />
          <MetricCard label="退化" value={String(regressions.length)} tone="bad" />
          <MetricCard label="改进" value={String(improvements.length)} tone="good" />
          <MetricCard
            label="共有用例"
            value={String(numberSummary(report.summary, "common_cases") ?? 0)}
            tone="neutral"
          />
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <MetricDeltaTable metrics={report.metric_deltas} />
        <FailureDeltaPanel failures={report.failure_distribution_delta} />
      </section>

      <CaseComparisonTable rows={report.case_comparisons} />

      <section className="grid gap-6 lg:grid-cols-2">
        <JsonPanel title="基线配置" value={report.baseline_run.config_snapshot} />
        <JsonPanel title="候选配置" value={report.candidate_run.config_snapshot} />
      </section>
    </div>
  );
}

function MetricDeltaTable({ metrics }: { metrics: EvaluationMetricDelta[] }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">指标变化</h2>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-slate-500">
              <th className="py-2 pr-3 font-medium">指标</th>
              <th className="py-2 pr-3 font-medium">基线</th>
              <th className="py-2 pr-3 font-medium">候选</th>
              <th className="py-2 pr-3 font-medium">变化量</th>
              <th className="py-2 font-medium">影响</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => (
              <tr key={metric.name} className="border-b border-border">
                <td className="py-3 pr-3 font-medium text-slate-950">{metricLabel(metric.name)}</td>
                <td className="py-3 pr-3 text-slate-700">{formatMetric(metric.name, metric.baseline)}</td>
                <td className="py-3 pr-3 text-slate-700">
                  {formatMetric(metric.name, metric.candidate)}
                </td>
                <td className={`py-3 pr-3 font-medium ${metricTextClass(metricTone(metric))}`}>
                  {deltaLabel(metric)}
                </td>
                <td className="py-3">
                  <span
                    className={`rounded-full px-2 py-1 text-xs font-medium ${toneBadgeClass(
                      metricTone(metric)
                    )}`}
                  >
                    {metricTone(metric)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FailureDeltaPanel({ failures }: { failures: Record<string, number> }) {
  const entries = Object.entries(failures).sort(([left], [right]) => left.localeCompare(right));
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">失败分布</h2>
      {entries.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">失败分布无变化。</p>
      ) : (
        <div className="mt-4 space-y-2">
          {entries.map(([category, delta]) => (
            <div
              key={category}
              className="flex items-center justify-between gap-3 rounded-md border border-border p-3 text-sm"
            >
              <span className="font-medium text-slate-950">{category}</span>
              <span className={delta > 0 ? "text-red-700" : delta < 0 ? "text-emerald-700" : "text-slate-500"}>
                {delta > 0 ? "+" : ""}
                {delta}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function CaseComparisonTable({ rows }: { rows: EvaluationCaseComparison[] }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">用例对比</h2>
      {rows.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">没有可对比的用例结果。</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase text-slate-500">
                <th className="py-2 pr-3 font-medium">用例</th>
                <th className="py-2 pr-3 font-medium">状态</th>
                <th className="py-2 pr-3 font-medium">基线</th>
                <th className="py-2 pr-3 font-medium">候选</th>
                <th className="py-2 pr-3 font-medium">耗时</th>
                <th className="py-2 font-medium">结果摘要</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.case_id} className="border-b border-border align-top">
                  <td className="py-3 pr-3">
                    <p className="font-medium text-slate-950">{row.case_id}</p>
                    <p className="mt-1 max-w-sm truncate text-xs text-slate-500">
                      {row.question ?? row.expected_file ?? "n/a"}
                    </p>
                  </td>
                  <td className="py-3 pr-3">
                    <span className={`rounded-full px-2 py-1 text-xs font-medium ${caseStatusClass(row.status)}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-700">
                    {caseRunLabel(row.baseline_status, row.baseline_failure_category)}
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-700">
                    {caseRunLabel(row.candidate_status, row.candidate_failure_category)}
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-700">
                    {row.latency_delta_ms === null ? "n/a" : `${signed(row.latency_delta_ms)}ms`}
                  </td>
                  <td className="py-3 font-mono text-xs text-slate-700">
                    {compactJson({
                      baseline: row.baseline_result,
                      candidate: row.candidate_result
                    })}
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

function MetricCard({
  label,
  value,
  tone
}: {
  label: string;
  value: string;
  tone: "good" | "bad" | "neutral";
}) {
  return (
    <div className={`rounded-md border p-3 ${metricCardClass(tone)}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
        <code>{JSON.stringify(value ?? {}, null, 2)}</code>
      </pre>
    </section>
  );
}

function defaultRunPair(runs: EvaluationRun[]) {
  const completed = runs.filter((run) => run.status === "completed");
  const candidate = completed[0];
  if (!candidate) {
    return { baselineRunId: "", candidateRunId: "" };
  }

  const baseline =
    completed.find(
      (run) =>
        run.id !== candidate.id &&
        run.task_type === candidate.task_type &&
        run.dataset_id === candidate.dataset_id
    ) ??
    completed.find((run) => run.id !== candidate.id && run.task_type === candidate.task_type) ??
    completed.find((run) => run.id !== candidate.id);

  return {
    baselineRunId: baseline?.id ?? "",
    candidateRunId: candidate.id
  };
}

function runLabel(run: EvaluationRun) {
  const dataset = run.dataset_id ? `数据集 ${run.dataset_id.slice(0, 8)}` : "manual";
  return `${run.name || run.id} · ${run.task_type} · ${dataset} · ${new Date(
    run.created_at
  ).toLocaleString()}`;
}

function modelLabel(run: EvaluationRun) {
  const config = run.config_snapshot;
  const llmModel = stringValue(config.llm_model);
  const embeddingModel = stringValue(config.embedding_model);
  if (run.task_type === "fix") {
    return `LLM ${stringValue(config.llm_provider) ?? "n/a"} / ${llmModel ?? "n/a"}`;
  }
  return `Embedding ${stringValue(config.embedding_provider) ?? "n/a"} / ${
    embeddingModel ?? "n/a"
  }`;
}

function metricLabel(name: string) {
  const labels: Record<string, string> = {
    fix_success_rate: "修复成功率",
    final_verified_fix_rate: "最终验证通过率",
    avg_latency_sec: "平均耗时",
    avg_tool_calls: "平均工具调用次数",
    passed: "通过",
    failed: "失败"
  };
  return /^recall_at_\d+$/.test(name) ? `Recall@${name.replace("recall_at_", "")}` : labels[name] ?? name;
}

function formatMetric(name: string, value: number | null) {
  if (value === null) {
    return "n/a";
  }
  if (/^recall_at_\d+$/.test(name) || name.endsWith("_rate")) {
    return `${Math.round(value * 100)}%`;
  }
  if (name === "avg_latency_sec") {
    return `${value.toFixed(3)}s`;
  }
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(2);
}

function deltaLabel(metric: EvaluationMetricDelta) {
  if (metric.delta === null) {
    return "n/a";
  }
  const prefix = metric.delta > 0 ? "+" : "";
  if (/^recall_at_\d+$/.test(metric.name) || metric.name.endsWith("_rate")) {
    return `${prefix}${Math.round(metric.delta * 100)}个百分点`;
  }
  if (metric.name === "avg_latency_sec") {
    return `${prefix}${metric.delta.toFixed(3)}s`;
  }
  return `${prefix}${Number.isInteger(metric.delta) ? metric.delta : metric.delta.toFixed(2)}`;
}

function metricTone(metric: EvaluationMetricDelta): "good" | "bad" | "neutral" {
  if (metric.delta === null || metric.delta === 0 || metric.direction === "neutral") {
    return "neutral";
  }
  if (metric.direction === "higher_is_better") {
    return metric.delta > 0 ? "good" : "bad";
  }
  return metric.delta < 0 ? "good" : "bad";
}

function verdictClass(verdict: EvaluationRunCompare["verdict"]) {
  if (verdict === "pass") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (verdict === "regression") {
    return "bg-red-100 text-red-700";
  }
  return "bg-amber-100 text-amber-800";
}

function gateStatusClass(status: EvaluationGateResult["status"]) {
  if (status === "passed") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (status === "failed") {
    return "bg-red-100 text-red-700";
  }
  return "bg-amber-100 text-amber-800";
}

function checkStatusClass(passed: boolean | null) {
  if (passed === true) {
    return "bg-emerald-100 text-emerald-700";
  }
  if (passed === false) {
    return "bg-red-100 text-red-700";
  }
  return "bg-amber-100 text-amber-800";
}

function checkLabel(name: string) {
  const labels: Record<string, string> = {
    matching_dataset_snapshot: "数据集快照一致",
    compatible_runs: "运行兼容性",
    primary_metric_drop: "主要指标降幅",
    case_regressions: "退化用例数",
    avg_latency_increase: "平均耗时增量",
    avg_tool_call_increase: "平均工具调用次数增量"
  };
  return labels[name] ?? name;
}

function formatCheckValue(value: number | string | boolean | null) {
  if (value === null) {
    return "n/a";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
}

function metricCardClass(tone: "good" | "bad" | "neutral") {
  if (tone === "good") {
    return "border-emerald-200 bg-emerald-50";
  }
  if (tone === "bad") {
    return "border-red-200 bg-red-50";
  }
  return "border-border bg-white";
}

function toneBadgeClass(tone: "good" | "bad" | "neutral") {
  if (tone === "good") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (tone === "bad") {
    return "bg-red-100 text-red-700";
  }
  return "bg-slate-100 text-slate-700";
}

function metricTextClass(tone: "good" | "bad" | "neutral") {
  if (tone === "good") {
    return "text-emerald-700";
  }
  if (tone === "bad") {
    return "text-red-700";
  }
  return "text-slate-700";
}

function caseStatusClass(status: EvaluationCaseComparison["status"]) {
  if (status === "regressed") {
    return "bg-red-100 text-red-700";
  }
  if (status === "improved") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (status === "baseline_only" || status === "candidate_only") {
    return "bg-amber-100 text-amber-800";
  }
  return "bg-slate-100 text-slate-700";
}

function caseRunLabel(status: string | null, failure: string | null) {
  if (!status && !failure) {
    return "n/a";
  }
  return failure ? `${status ?? "unknown"} · ${failure}` : status ?? "unknown";
}

function compactJson(value: unknown) {
  const raw = JSON.stringify(value ?? {}, null, 2);
  return raw.length > 420 ? `${raw.slice(0, 420)}...` : raw;
}

function signed(value: number) {
  return value > 0 ? `+${value}` : String(value);
}

function numberSummary(summary: Record<string, unknown>, key: string) {
  const value = summary[key];
  return typeof value === "number" ? value : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
