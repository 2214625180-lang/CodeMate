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
      setError(err instanceof Error ? err.message : "Failed to load evaluation runs");
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
      setError(err instanceof Error ? err.message : "Failed to load benchmark datasets");
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!baselineRunId || !candidateRunId || baselineRunId === candidateRunId) {
      setError("Choose two different evaluation runs.");
      return;
    }

    setIsComparing(true);
    setError(null);
    try {
      const data = await compareEvaluationRuns(baselineRunId, candidateRunId);
      setReport(data);
      setGateResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to compare evaluation runs");
    } finally {
      setIsComparing(false);
    }
  }

  async function handleGateCheck() {
    if (!candidateRun || !candidateDataset) {
      setError("Choose a candidate run that belongs to a benchmark dataset.");
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
      setError(err instanceof Error ? err.message : "Failed to evaluate regression gate");
    } finally {
      setIsCheckingGate(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">Evaluation Center</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">Regression Report</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Compare two completed benchmark runs to spot metric regressions, changed failures, and
            case-level behavior shifts.
          </p>
        </div>
        <Link
          href="/evaluations"
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Evaluation Center
        </Link>
      </div>

      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <RunSelect
            id="baseline-run"
            label="Baseline"
            value={baselineRunId}
            runs={completedRuns}
            onChange={setBaselineRunId}
          />
          <RunSelect
            id="candidate-run"
            label="Candidate"
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
              {isComparing ? "Comparing..." : "Generate report"}
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <RunContext run={baselineRun} title="Baseline context" />
          <RunContext run={candidateRun} title="Candidate context" />
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <div className="text-sm text-slate-600">
            {candidateDataset ? (
              <span>
                Gate policy: {candidateDataset.name} · baseline{" "}
                {candidateDataset.baseline_run_id
                  ? candidateDataset.baseline_run_id.slice(0, 8)
                  : "not set"}
              </span>
            ) : (
              <span>Gate policy requires a candidate run created from a benchmark dataset.</span>
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
            {isCheckingGate ? "Checking gate..." : "Evaluate gate"}
          </button>
        </div>
      </form>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      {isLoading ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          Loading evaluation runs...
        </section>
      ) : completedRuns.length < 2 ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          At least two completed evaluation runs are required.
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
        <option value="">Select run</option>
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
        {title}: none selected
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-slate-50 p-3">
      <p className="text-sm font-semibold text-slate-950">{title}</p>
      <div className="mt-2 grid gap-1 text-xs text-slate-600">
        <span>{run.name || run.id}</span>
        <span>
          {run.task_type} · dataset {run.dataset_id ? run.dataset_id.slice(0, 8) : "manual"} · v
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
          <h2 className="text-lg font-semibold text-slate-950">Regression gate</h2>
          <p className="mt-1 text-sm text-slate-600">
            {result.dataset.name} · baseline {result.baseline_run.name || result.baseline_run.id}
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
          label="Allowed metric drop"
          value={`${Math.round(result.policy.max_primary_metric_drop * 1000) / 10}%`}
          tone="neutral"
        />
        <MetricCard
          label="Max regressions"
          value={String(result.policy.max_regressed_cases)}
          tone="neutral"
        />
        <MetricCard
          label="Incompatible"
          value={result.policy.allow_incompatible ? "allowed" : "blocked"}
          tone="neutral"
        />
        <MetricCard
          label="Snapshot"
          value={result.policy.require_matching_dataset_snapshot ? "required" : "ignored"}
          tone="neutral"
        />
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-slate-500">
              <th className="py-2 pr-3 font-medium">Check</th>
              <th className="py-2 pr-3 font-medium">Status</th>
              <th className="py-2 pr-3 font-medium">Observed</th>
              <th className="py-2 pr-3 font-medium">Threshold</th>
              <th className="py-2 font-medium">Rule</th>
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
            <h2 className="text-lg font-semibold text-slate-950">Report summary</h2>
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
          <MetricCard label="Regressions" value={String(regressions.length)} tone="bad" />
          <MetricCard label="Improvements" value={String(improvements.length)} tone="good" />
          <MetricCard
            label="Common cases"
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
        <JsonPanel title="Baseline config" value={report.baseline_run.config_snapshot} />
        <JsonPanel title="Candidate config" value={report.candidate_run.config_snapshot} />
      </section>
    </div>
  );
}

function MetricDeltaTable({ metrics }: { metrics: EvaluationMetricDelta[] }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">Metric deltas</h2>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-slate-500">
              <th className="py-2 pr-3 font-medium">Metric</th>
              <th className="py-2 pr-3 font-medium">Baseline</th>
              <th className="py-2 pr-3 font-medium">Candidate</th>
              <th className="py-2 pr-3 font-medium">Delta</th>
              <th className="py-2 font-medium">Impact</th>
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
      <h2 className="text-lg font-semibold text-slate-950">Failure distribution</h2>
      {entries.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No failure distribution changes.</p>
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
      <h2 className="text-lg font-semibold text-slate-950">Case comparison</h2>
      {rows.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No case results to compare.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase text-slate-500">
                <th className="py-2 pr-3 font-medium">Case</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Baseline</th>
                <th className="py-2 pr-3 font-medium">Candidate</th>
                <th className="py-2 pr-3 font-medium">Latency</th>
                <th className="py-2 font-medium">Result summary</th>
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
  const dataset = run.dataset_id ? `dataset ${run.dataset_id.slice(0, 8)}` : "manual";
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
    fix_success_rate: "Fix success",
    final_verified_fix_rate: "Final verified fix",
    avg_latency_sec: "Avg latency",
    avg_tool_calls: "Avg tool calls",
    passed: "Passed",
    failed: "Failed"
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
    return `${prefix}${Math.round(metric.delta * 100)}pp`;
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
    matching_dataset_snapshot: "Matching dataset snapshot",
    compatible_runs: "Compatible runs",
    primary_metric_drop: "Primary metric drop",
    case_regressions: "Case regressions",
    avg_latency_increase: "Avg latency increase",
    avg_tool_call_increase: "Avg tool call increase"
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
