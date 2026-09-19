"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getEvaluationDatasetHistory, listEvaluationDatasets } from "@/lib/api";
import type {
  EvaluationDataset,
  EvaluationHistory,
  EvaluationHistoryFilters,
  EvaluationHistoryRun
} from "@/lib/types";

type TimeRange = "all" | "7d" | "30d" | "90d" | "custom";
type RunStatusFilter = EvaluationHistoryRun["status"] | "all";
type GateStatusFilter = EvaluationHistoryRun["gate_status"] | "all";

export function HistoryDashboardClient({ initialDatasetId }: { initialDatasetId: string }) {
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [datasetId, setDatasetId] = useState(initialDatasetId);
  const [history, setHistory] = useState<EvaluationHistory | null>(null);
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(true);
  const [isLoadingHistory, setIsLoadingHistory] = useState(Boolean(initialDatasetId));
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");
  const [customFromDate, setCustomFromDate] = useState("");
  const [customToDate, setCustomToDate] = useState("");
  const [runStatus, setRunStatus] = useState<RunStatusFilter>("all");
  const [gateStatus, setGateStatus] = useState<GateStatusFilter>("all");
  const [providerFilter, setProviderFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [limit, setLimit] = useState(50);

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId) ?? history?.dataset ?? null,
    [datasets, datasetId, history]
  );

  const historyFilters = useMemo<EvaluationHistoryFilters>(
    () => ({
      limit,
      createdAfter: createdAfterForRange(timeRange, customFromDate),
      createdBefore: createdBeforeForRange(timeRange, customToDate),
      status: runStatus === "all" ? null : runStatus,
      gateStatus: gateStatus === "all" ? null : gateStatus,
      provider: providerFilter.trim() || null,
      model: modelFilter.trim() || null
    }),
    [customFromDate, customToDate, gateStatus, limit, modelFilter, providerFilter, runStatus, timeRange]
  );

  const reportMarkdown = useMemo(
    () => (history ? renderTrendReportMarkdown(history) : ""),
    [history]
  );

  const loadDatasets = useCallback(async () => {
    try {
      const data = await listEvaluationDatasets();
      setDatasets(data);
      if (!datasetId && data[0]) {
        setDatasetId(data[0].id);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载基准数据集失败");
    } finally {
      setIsLoadingDatasets(false);
    }
  }, [datasetId]);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  const loadHistory = useCallback(async () => {
    if (!datasetId) {
      setHistory(null);
      setIsLoadingHistory(false);
      return;
    }
    setIsLoadingHistory(true);
    try {
      const data = await getEvaluationDatasetHistory(datasetId, historyFilters);
      setHistory(data);
      setError(null);
    } catch (err) {
      setHistory(null);
      setError(err instanceof Error ? err.message : "加载评测历史失败");
    } finally {
      setIsLoadingHistory(false);
    }
  }, [datasetId, historyFilters]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  function exportTrendReport(format: "json" | "markdown") {
    if (!history) {
      return;
    }
    const content =
      format === "json"
        ? `${JSON.stringify(
            {
              report_version: "1",
              generated_at: new Date().toISOString(),
              history
            },
            null,
            2
          )}\n`
        : reportMarkdown;
    downloadText(
      content,
      trendReportFilename(history, format === "json" ? "json" : "md"),
      format === "json" ? "application/json" : "text/markdown"
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">评测中心</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">评测历史</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            跟踪各次评测的基准质量、耗时、门禁状态和失败用例。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/evaluations"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            评测中心
          </Link>
          <Link
            href="/evaluations/datasets"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            基准数据集
          </Link>
          <button
            type="button"
            disabled={!history}
            onClick={() => exportTrendReport("json")}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
          >
            导出 JSON
          </button>
          <button
            type="button"
            disabled={!history}
            onClick={() => exportTrendReport("markdown")}
            className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            导出 Markdown
          </button>
        </div>
      </div>

      <section className="rounded-lg border border-border bg-white p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[260px] flex-1">
            <label htmlFor="history-dataset" className="text-sm font-medium text-slate-700">
              基准数据集
            </label>
            <select
              id="history-dataset"
              value={datasetId}
              disabled={isLoadingDatasets || datasets.length === 0}
              onChange={(event) => setDatasetId(event.target.value)}
              className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500 disabled:bg-slate-100 disabled:text-slate-400"
            >
              {datasets.length === 0 ? <option value="">无数据集</option> : null}
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name} v{dataset.version} ({dataset.task_type})
                </option>
              ))}
            </select>
          </div>
          {selectedDataset ? (
            <div className="rounded-md border border-border bg-slate-50 px-3 py-2 text-sm text-slate-600">
              {selectedDataset.task_type} · {selectedDataset.cases_json.length} 个用例 · 基线{" "}
              {selectedDataset.baseline_run_id
                ? selectedDataset.baseline_run_id.slice(0, 8)
              : "未设置"}
            </div>
          ) : null}
        </div>
        <HistoryFiltersPanel
          timeRange={timeRange}
          setTimeRange={setTimeRange}
          customFromDate={customFromDate}
          setCustomFromDate={setCustomFromDate}
          customToDate={customToDate}
          setCustomToDate={setCustomToDate}
          runStatus={runStatus}
          setRunStatus={setRunStatus}
          gateStatus={gateStatus}
          setGateStatus={setGateStatus}
          providerFilter={providerFilter}
          setProviderFilter={setProviderFilter}
          modelFilter={modelFilter}
          setModelFilter={setModelFilter}
          limit={limit}
          setLimit={setLimit}
        />
      </section>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      {isLoadingHistory ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          正在加载评测历史…
        </section>
      ) : history ? (
        <>
          <HistorySummary history={history} />
          <section className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
            <MetricTrend history={history} />
            <GateStatusPanel history={history} />
          </section>
          <RecentHistoryRuns history={history} />
        </>
      ) : (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          请选择基准数据集以查看历史记录。
        </section>
      )}
    </div>
  );
}

function HistoryFiltersPanel({
  timeRange,
  setTimeRange,
  customFromDate,
  setCustomFromDate,
  customToDate,
  setCustomToDate,
  runStatus,
  setRunStatus,
  gateStatus,
  setGateStatus,
  providerFilter,
  setProviderFilter,
  modelFilter,
  setModelFilter,
  limit,
  setLimit
}: {
  timeRange: TimeRange;
  setTimeRange: (value: TimeRange) => void;
  customFromDate: string;
  setCustomFromDate: (value: string) => void;
  customToDate: string;
  setCustomToDate: (value: string) => void;
  runStatus: RunStatusFilter;
  setRunStatus: (value: RunStatusFilter) => void;
  gateStatus: GateStatusFilter;
  setGateStatus: (value: GateStatusFilter) => void;
  providerFilter: string;
  setProviderFilter: (value: string) => void;
  modelFilter: string;
  setModelFilter: (value: string) => void;
  limit: number;
  setLimit: (value: number) => void;
}) {
  function resetFilters() {
    setTimeRange("30d");
    setCustomFromDate("");
    setCustomToDate("");
    setRunStatus("all");
    setGateStatus("all");
    setProviderFilter("");
    setModelFilter("");
    setLimit(50);
  }

  return (
    <div className="mt-5 border-t border-border pt-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <label htmlFor="history-time-range" className="text-sm font-medium text-slate-700">
            时间范围
          </label>
          <select
            id="history-time-range"
            value={timeRange}
            onChange={(event) => setTimeRange(event.target.value as TimeRange)}
            className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500"
          >
            <option value="7d">最近 7 天</option>
            <option value="30d">最近 30 天</option>
            <option value="90d">最近 90 天</option>
            <option value="all">全部时间</option>
            <option value="custom">自定义</option>
          </select>
        </div>

        <div>
          <label htmlFor="history-run-status" className="text-sm font-medium text-slate-700">
            运行状态
          </label>
          <select
            id="history-run-status"
            value={runStatus}
            onChange={(event) => setRunStatus(event.target.value as RunStatusFilter)}
            className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500"
          >
            <option value="all">全部</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
            <option value="running">运行中</option>
          </select>
        </div>

        <div>
          <label htmlFor="history-gate-status" className="text-sm font-medium text-slate-700">
            门禁状态
          </label>
          <select
            id="history-gate-status"
            value={gateStatus}
            onChange={(event) => setGateStatus(event.target.value as GateStatusFilter)}
            className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500"
          >
            <option value="all">全部</option>
            <option value="passed">通过</option>
            <option value="failed">失败</option>
            <option value="inconclusive">无法判定</option>
            <option value="not_evaluated">未评估</option>
          </select>
        </div>

        <div>
          <label htmlFor="history-limit" className="text-sm font-medium text-slate-700">
            运行记录
          </label>
          <input
            id="history-limit"
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(event) => setLimit(clamp(Number(event.target.value), 1, 100))}
            className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
          />
        </div>
      </div>

      {timeRange === "custom" ? (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="history-from-date" className="text-sm font-medium text-slate-700">
              开始时间
            </label>
            <input
              id="history-from-date"
              type="date"
              value={customFromDate}
              onChange={(event) => setCustomFromDate(event.target.value)}
              className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
            />
          </div>
          <div>
            <label htmlFor="history-to-date" className="text-sm font-medium text-slate-700">
              结束时间
            </label>
            <input
              id="history-to-date"
              type="date"
              value={customToDate}
              onChange={(event) => setCustomToDate(event.target.value)}
              className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
            />
          </div>
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <div>
          <label htmlFor="history-provider" className="text-sm font-medium text-slate-700">
            服务商名称包含
          </label>
          <input
            id="history-provider"
            value={providerFilter}
            onChange={(event) => setProviderFilter(event.target.value)}
            placeholder="openai, mock, deepseek"
            className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
          />
        </div>
        <div>
          <label htmlFor="history-model" className="text-sm font-medium text-slate-700">
            模型名称包含
          </label>
          <input
            id="history-model"
            value={modelFilter}
            onChange={(event) => setModelFilter(event.target.value)}
            placeholder="gpt-4.1, text-embedding"
            className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
          />
        </div>
        <div className="flex items-end">
          <button
            type="button"
            onClick={resetFilters}
            className="min-h-10 rounded-md border border-border px-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            重置
          </button>
        </div>
      </div>
    </div>
  );
}

function HistorySummary({ history }: { history: EvaluationHistory }) {
  const summary = history.summary;
  const latestMetric = numberValue(summary.latest_primary_metric);
  const latestDelta = numberValue(summary.latest_primary_metric_delta);
  const avgLatency = numberValue(summary.avg_latency_sec);
  const avgToolCalls = numberValue(summary.avg_tool_calls);
  const completedCount = numberValue(summary.completed_count) ?? 0;
  const runCount = numberValue(summary.run_count) ?? history.runs.length;

  return (
    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <SummaryCard
        label={metricLabel(history.primary_metric_name)}
        value={formatPercent(latestMetric)}
        detail={latestDelta === null ? "无上一次已完成的运行" : `${formatDelta(latestDelta)} 与上一次相比`}
      />
      <SummaryCard
        label="已完成运行"
        value={`${completedCount}/${runCount}`}
        detail={`${numberValue(summary.failed_run_count) ?? 0} 次失败 · ${numberValue(summary.running_count) ?? 0} 次运行中`}
      />
      <SummaryCard
        label="平均耗时"
        value={formatSeconds(avgLatency)}
        detail="Completed runs"
      />
      <SummaryCard
        label="平均工具调用次数"
        value={avgToolCalls === null ? "n/a" : formatNumber(avgToolCalls)}
        detail={history.dataset.task_type === "fix" ? "代码修复运行" : "检索运行"}
      />
    </section>
  );
}

function SummaryCard({
  label,
  value,
  detail
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-white p-5">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-3 text-2xl font-semibold text-slate-950">{value}</p>
      <p className="mt-2 text-sm text-slate-500">{detail}</p>
    </div>
  );
}

function MetricTrend({ history }: { history: EvaluationHistory }) {
  const completedRuns = useMemo(
    () =>
      history.runs
        .filter((run) => run.status === "completed" && run.primary_metric_value !== null)
        .slice()
        .reverse(),
    [history.runs]
  );

  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">
            {metricLabel(history.primary_metric_name)} 趋势
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            {completedRuns.length} 次已完成运行 · 最新记录在右侧
          </p>
        </div>
        <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
          {history.dataset.task_type}
        </span>
      </div>

      {completedRuns.length === 0 ? (
        <p className="mt-8 text-sm text-slate-500">暂无包含指标数据的已完成运行。</p>
      ) : (
        <div className="mt-6">
          <TrendSvg runs={completedRuns} />
          <div className="mt-4 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
            <span>最早： {shortRunLabel(completedRuns[0])}</span>
            <span className="sm:text-right">
              最新： {shortRunLabel(completedRuns[completedRuns.length - 1])}
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

function TrendSvg({ runs }: { runs: EvaluationHistoryRun[] }) {
  const width = 720;
  const height = 220;
  const padding = 32;
  const values = runs.map((run) => run.primary_metric_value ?? 0);
  const minValue = Math.min(0, ...values);
  const maxValue = Math.max(1, ...values);
  const range = Math.max(0.0001, maxValue - minValue);
  const pointFor = (value: number, index: number) => {
    const x =
      runs.length === 1
        ? width / 2
        : padding + (index / (runs.length - 1)) * (width - padding * 2);
    const y = height - padding - ((value - minValue) / range) * (height - padding * 2);
    return { x, y };
  };
  const points = values.map((value, index) => pointFor(value, index));
  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-[220px] w-full rounded-md border border-border bg-white"
      role="img"
      aria-label="主要指标趋势"
    >
      {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
        const y = height - padding - tick * (height - padding * 2);
        return (
          <g key={tick}>
            <line x1={padding} x2={width - padding} y1={y} y2={y} stroke="#e2e8f0" />
            <text x={8} y={y + 4} className="fill-slate-500 text-[11px]">
              {Math.round((minValue + tick * range) * 100)}%
            </text>
          </g>
        );
      })}
      <polyline points={polyline} fill="none" stroke="#0f766e" strokeWidth="3" />
      {points.map((point, index) => (
        <g key={runs[index].id}>
          <circle cx={point.x} cy={point.y} r="4" fill="#0f766e" />
          <title>
            {runs[index].name || runs[index].id}: {formatPercent(runs[index].primary_metric_value)}
          </title>
        </g>
      ))}
    </svg>
  );
}

function GateStatusPanel({ history }: { history: EvaluationHistory }) {
  const statuses: Array<{
    key: EvaluationHistoryRun["gate_status"];
    label: string;
    className: string;
  }> = [
    { key: "passed", label: "通过", className: "bg-emerald-50 text-emerald-700" },
    { key: "failed", label: "失败", className: "bg-red-50 text-red-700" },
    { key: "inconclusive", label: "无法判定", className: "bg-amber-50 text-amber-700" },
    { key: "not_evaluated", label: "未评估", className: "bg-slate-100 text-slate-600" }
  ];

  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">门禁状态</h2>
      <div className="mt-5 space-y-3">
        {statuses.map((status) => (
          <div key={status.key} className="flex items-center justify-between gap-3">
            <span className={`rounded-md px-2 py-1 text-xs font-medium ${status.className}`}>
              {status.label}
            </span>
            <span className="text-sm font-semibold text-slate-950">
              {history.gate_status_counts[status.key] ?? 0}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-6 border-t border-border pt-4">
        <p className="text-sm font-medium text-slate-700">基线</p>
        <p className="mt-1 break-all text-sm text-slate-500">
          {history.baseline_run_id ?? "未配置基线"}
        </p>
      </div>
    </section>
  );
}

function RecentHistoryRuns({ history }: { history: EvaluationHistory }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">运行记录</h2>
        <span className="text-sm text-slate-500">{history.runs.length} 次近期运行</span>
      </div>

      {history.runs.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">此数据集暂无评测记录。</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase text-slate-500">
                <th className="py-2 pr-4 font-medium">运行</th>
                <th className="py-2 pr-4 font-medium">快照</th>
                <th className="py-2 pr-4 font-medium">状态</th>
                <th className="py-2 pr-4 font-medium">门禁</th>
                <th className="py-2 pr-4 font-medium">{metricLabel(history.primary_metric_name)}</th>
                <th className="py-2 pr-4 font-medium">变化量</th>
                <th className="py-2 pr-4 font-medium">耗时</th>
                <th className="py-2 pr-4 font-medium">退化</th>
                <th className="py-2 pr-4 font-medium">模型</th>
              </tr>
            </thead>
            <tbody>
              {history.runs.map((run) => (
                <tr key={run.id} className="border-b border-border last:border-0">
                  <td className="max-w-[280px] py-3 pr-4">
                    <Link
                      href={`/evaluations/artifact?runId=${run.id}`}
                      className="font-medium text-slate-950 hover:text-slate-700"
                    >
                      {run.name || run.id}
                    </Link>
                    <span className="mt-1 block text-xs text-slate-500">
                      v{run.dataset_version ?? "n/a"} · {new Date(run.created_at).toLocaleString()}
                    </span>
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-slate-600">
                    <span title={run.dataset_snapshot_id ?? undefined}>
                      {shortSnapshotLabel(run.dataset_snapshot_id)}
                    </span>
                  </td>
                  <td className="py-3 pr-4">
                    <StatusBadge value={run.status} />
                  </td>
                  <td className="py-3 pr-4">
                    <GateBadge value={run.gate_status} />
                  </td>
                  <td className="py-3 pr-4 font-medium text-slate-950">
                    {formatPercent(run.primary_metric_value)}
                  </td>
                  <td className="py-3 pr-4">{formatDelta(run.primary_metric_delta)}</td>
                  <td className="py-3 pr-4">{formatSeconds(run.avg_latency_sec)}</td>
                  <td className="py-3 pr-4">{run.regressions ?? "n/a"}</td>
                  <td className="max-w-[220px] py-3 pr-4 text-slate-600">
                    <span className="block truncate">{run.provider ?? "n/a"}</span>
                    <span className="block truncate text-xs text-slate-500">{run.model ?? "n/a"}</span>
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

function StatusBadge({ value }: { value: EvaluationHistoryRun["status"] }) {
  const className =
    value === "completed"
      ? "bg-emerald-50 text-emerald-700"
      : value === "failed"
        ? "bg-red-50 text-red-700"
        : "bg-amber-50 text-amber-700";
  return <span className={`rounded-md px-2 py-1 text-xs font-medium ${className}`}>{value}</span>;
}

function GateBadge({ value }: { value: EvaluationHistoryRun["gate_status"] }) {
  const className =
    value === "passed"
      ? "bg-emerald-50 text-emerald-700"
      : value === "failed"
        ? "bg-red-50 text-red-700"
        : value === "inconclusive"
          ? "bg-amber-50 text-amber-700"
          : "bg-slate-100 text-slate-600";
  return (
    <span className={`whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium ${className}`}>
      {value.replace("_", " ")}
    </span>
  );
}

function metricLabel(metricName: string) {
  const labels: Record<string, string> = {
    fix_success_rate: "修复成功率",
    final_verified_fix_rate: "最终验证通过率",
    avg_latency_sec: "平均耗时",
    avg_tool_calls: "平均工具调用次数"
  };
  return /^recall_at_\d+$/.test(metricName)
    ? `Recall@${metricName.replace("recall_at_", "")}`
    : labels[metricName] ?? metricName;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPercent(value: number | null) {
  return value === null ? "n/a" : `${Math.round(value * 1000) / 10}%`;
}

function formatDelta(value: number | null) {
  if (value === null) {
    return "n/a";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${Math.round(value * 1000) / 10}%`;
}

function formatSeconds(value: number | null) {
  return value === null ? "n/a" : `${Math.round(value * 1000) / 1000}s`;
}

function formatNumber(value: number) {
  return String(Math.round(value * 100) / 100);
}

function shortRunLabel(run: EvaluationHistoryRun) {
  return `${run.name || run.id.slice(0, 8)} · ${formatPercent(run.primary_metric_value)}`;
}

function shortSnapshotLabel(snapshotId: string | null) {
  return snapshotId ? snapshotId.slice(0, 8) : "n/a";
}

function createdAfterForRange(timeRange: TimeRange, customFromDate: string) {
  if (timeRange === "all") {
    return null;
  }
  if (timeRange === "custom") {
    return customFromDate ? new Date(`${customFromDate}T00:00:00`).toISOString() : null;
  }
  const days = timeRange === "7d" ? 7 : timeRange === "30d" ? 30 : 90;
  const start = new Date();
  start.setDate(start.getDate() - days);
  return start.toISOString();
}

function createdBeforeForRange(timeRange: TimeRange, customToDate: string) {
  if (timeRange !== "custom" || !customToDate) {
    return null;
  }
  return new Date(`${customToDate}T23:59:59`).toISOString();
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, Math.trunc(value)));
}

function renderTrendReportMarkdown(history: EvaluationHistory) {
  const summary = history.summary;
  const filters = history.filters ?? {};
  const failureDistribution = aggregateFailureDistribution(history.runs);
  const lines = [
    `# 评测趋势报告：${escapeMarkdown(history.dataset.name)}`,
    "",
    "## 摘要",
    "",
    "| 字段 | 值 |",
    "| --- | --- |",
    tableRow("数据集", `${history.dataset.name} (${history.dataset.id})`),
    tableRow("任务类型", history.dataset.task_type),
    tableRow("数据集版本", history.dataset.version),
    tableRow("基线运行", history.baseline_run_id ?? "未配置"),
    tableRow("主要指标", metricLabel(history.primary_metric_name)),
    tableRow("最新指标", formatPercent(numberValue(summary.latest_primary_metric))),
    tableRow("最新变化量", formatDelta(numberValue(summary.latest_primary_metric_delta))),
    tableRow("已完成运行", `${numberValue(summary.completed_count) ?? 0}/${numberValue(summary.run_count) ?? history.runs.length}`),
    tableRow("平均耗时", formatSeconds(numberValue(summary.avg_latency_sec))),
    tableRow("平均工具调用次数", formatNullableNumber(numberValue(summary.avg_tool_calls))),
    "",
    "## 筛选条件",
    "",
    "| 筛选项 | 值 |",
    "| --- | --- |",
    tableRow("数量上限", filters.limit ?? "n/a"),
    tableRow("创建时间晚于", filters.created_after ?? "all"),
    tableRow("创建时间早于", filters.created_before ?? "all"),
    tableRow("运行状态", filters.status ?? "all"),
    tableRow("门禁状态", filters.gate_status ?? "all"),
    tableRow("服务商", filters.provider ?? "all"),
    tableRow("模型", filters.model ?? "all"),
    "",
    "## 门禁状态统计",
    "",
    gateStatusMarkdownTable(history),
    "",
    "## 失败分布",
    "",
    failureDistributionMarkdownTable(failureDistribution),
    "",
    "## 运行记录",
    "",
    historyRunsMarkdownTable(history)
  ];
  return `${lines.join("\n").trim()}\n`;
}

function gateStatusMarkdownTable(history: EvaluationHistory) {
  const rows: Array<[string, number]> = [
    ["passed", history.gate_status_counts.passed ?? 0],
    ["failed", history.gate_status_counts.failed ?? 0],
    ["inconclusive", history.gate_status_counts.inconclusive ?? 0],
    ["not_evaluated", history.gate_status_counts.not_evaluated ?? 0]
  ];
  return [
    "| 门禁状态 | 数量 |",
    "| --- | ---: |",
    ...rows.map(([status, count]) => `| ${escapeTable(status)} | ${count} |`)
  ].join("\n");
}

function failureDistributionMarkdownTable(failures: Record<string, number>) {
  const entries = Object.entries(failures).sort((left, right) => right[1] - left[1]);
  if (entries.length === 0) {
    return "_筛选范围内无失败记录。_";
  }
  return [
    "| 失败类别 | 数量 |",
    "| --- | ---: |",
    ...entries.map(([category, count]) => `| ${escapeTable(category)} | ${count} |`)
  ].join("\n");
}

function historyRunsMarkdownTable(history: EvaluationHistory) {
  if (history.runs.length === 0) {
    return "_没有符合筛选条件的运行。_";
  }
  return [
    "| 运行 | 快照 | 状态 | 门禁 | 指标 | 变化量 | 耗时 | 退化数 | 服务商 | 模型 | 创建时间 |",
    "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ...history.runs.map((run) =>
      [
        escapeTable(run.name || run.id),
        escapeTable(run.dataset_snapshot_id ?? "n/a"),
        escapeTable(run.status),
        escapeTable(run.gate_status),
        escapeTable(formatPercent(run.primary_metric_value)),
        escapeTable(formatDelta(run.primary_metric_delta)),
        escapeTable(formatSeconds(run.avg_latency_sec)),
        escapeTable(run.regressions ?? "n/a"),
        escapeTable(run.provider ?? "n/a"),
        escapeTable(run.model ?? "n/a"),
        escapeTable(new Date(run.created_at).toLocaleString())
      ].join(" | ")
    ).map((row) => `| ${row} |`)
  ].join("\n");
}

function aggregateFailureDistribution(runs: EvaluationHistoryRun[]) {
  return runs.reduce<Record<string, number>>((accumulator, run) => {
    Object.entries(run.failure_distribution).forEach(([category, count]) => {
      accumulator[category] = (accumulator[category] ?? 0) + count;
    });
    return accumulator;
  }, {});
}

function tableRow(label: string, value: unknown) {
  return `| ${escapeTable(label)} | ${escapeTable(formatReportValue(value))} |`;
}

function formatReportValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  return String(value);
}

function formatNullableNumber(value: number | null) {
  return value === null ? "n/a" : formatNumber(value);
}

function trendReportFilename(history: EvaluationHistory, extension: "json" | "md") {
  const name = history.dataset.name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `evaluation-trend-${name || history.dataset.id}.${extension}`;
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

function escapeTable(value: unknown) {
  return escapeMarkdown(formatReportValue(value)).replace(/\|/g, "\\|").replace(/\n/g, " ");
}

function escapeMarkdown(value: string) {
  return value.replace(/`/g, "\\`");
}
