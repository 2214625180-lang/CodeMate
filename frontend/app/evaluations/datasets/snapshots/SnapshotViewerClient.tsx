"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  backfillEvaluationDatasetSnapshots,
  listEvaluationDatasetSnapshots,
  listEvaluationDatasets
} from "@/lib/api";
import {
  backfillReportFilename,
  buildEvaluationBackfillReport,
  renderEvaluationBackfillReportMarkdown
} from "@/lib/evaluationBackfillReport";
import type {
  EvaluationDataset,
  EvaluationDatasetSnapshot,
  EvaluationSnapshotBackfillResult
} from "@/lib/types";

type CaseDiffStatus = "added" | "removed" | "changed" | "unchanged";

type CaseDiffItem = {
  key: string;
  status: CaseDiffStatus;
  base: Record<string, unknown> | null;
  candidate: Record<string, unknown> | null;
};

type CaseDiff = {
  counts: Record<CaseDiffStatus, number>;
  items: CaseDiffItem[];
};

export function SnapshotViewerClient({ initialDatasetId }: { initialDatasetId: string }) {
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [datasetId, setDatasetId] = useState(initialDatasetId);
  const [snapshots, setSnapshots] = useState<EvaluationDatasetSnapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [compareSnapshotId, setCompareSnapshotId] = useState("");
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(true);
  const [isLoadingSnapshots, setIsLoadingSnapshots] = useState(Boolean(initialDatasetId));
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [backfillResult, setBackfillResult] =
    useState<EvaluationSnapshotBackfillResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId) ?? null,
    [datasets, datasetId]
  );
  const selectedSnapshot = useMemo(
    () => snapshots.find((snapshot) => snapshot.id === snapshotId) ?? snapshots[0] ?? null,
    [snapshotId, snapshots]
  );
  const compareSnapshot = useMemo(
    () =>
      snapshots.find((snapshot) => snapshot.id === compareSnapshotId) ??
      snapshots.find((snapshot) => snapshot.id !== selectedSnapshot?.id) ??
      null,
    [compareSnapshotId, selectedSnapshot, snapshots]
  );
  const diff = useMemo(
    () =>
      selectedSnapshot && compareSnapshot
        ? diffSnapshots(compareSnapshot, selectedSnapshot)
        : null,
    [compareSnapshot, selectedSnapshot]
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

  const loadSnapshots = useCallback(async () => {
    if (!datasetId) {
      setSnapshots([]);
      setSnapshotId("");
      setCompareSnapshotId("");
      setIsLoadingSnapshots(false);
      return;
    }
    setIsLoadingSnapshots(true);
    try {
      const data = await listEvaluationDatasetSnapshots(datasetId);
      setSnapshots(data);
      setSnapshotId((current) =>
        data.some((snapshot) => snapshot.id === current) ? current : data[0]?.id ?? ""
      );
      setCompareSnapshotId((current) =>
        data.some((snapshot) => snapshot.id === current) ? current : data[1]?.id ?? ""
      );
      setError(null);
    } catch (err) {
      setSnapshots([]);
      setError(err instanceof Error ? err.message : "加载数据集快照失败");
    } finally {
      setIsLoadingSnapshots(false);
    }
  }, [datasetId]);

  useEffect(() => {
    void loadSnapshots();
  }, [loadSnapshots]);

  async function runBackfill(dryRun: boolean) {
    if (!datasetId) {
      return;
    }
    setIsBackfilling(true);
    setError(null);
    try {
      const result = await backfillEvaluationDatasetSnapshots(datasetId, {
        dry_run: dryRun,
        create_missing_snapshots: true,
        include_details: true
      });
      setBackfillResult(result);
      if (!dryRun && result.backfilled > 0) {
        await loadSnapshots();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "回填数据集快照失败");
    } finally {
      setIsBackfilling(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">评测中心</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">数据集快照</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            查看不可变的基准用例快照，对比不同版本之间的用例变化。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/evaluations/datasets"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            基准数据集
          </Link>
          <Link
            href="/evaluations/history"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            历史记录
          </Link>
          <Link
            href="/evaluations"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            评测中心
          </Link>
        </div>
      </div>

      <section className="rounded-lg border border-border bg-white p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(220px,320px)_minmax(220px,320px)]">
          <div>
            <label htmlFor="snapshot-dataset" className="text-sm font-medium text-slate-700">
              基准数据集
            </label>
            <select
              id="snapshot-dataset"
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
          <SnapshotSelect
            id="candidate-snapshot"
            label="快照"
            value={selectedSnapshot?.id ?? ""}
            snapshots={snapshots}
            disabled={isLoadingSnapshots || snapshots.length === 0}
            onChange={setSnapshotId}
          />
          <SnapshotSelect
            id="base-snapshot"
            label="对比版本"
            value={compareSnapshot?.id ?? ""}
            snapshots={snapshots}
            disabled={isLoadingSnapshots || snapshots.length < 2}
            onChange={setCompareSnapshotId}
          />
        </div>
        {selectedDataset ? (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-xs text-slate-500">
              {selectedDataset.task_type} · 当前版本 v{selectedDataset.version} ·{" "}
              {selectedDataset.cases_json.length} 当前用例
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={isBackfilling}
                onClick={() => void runBackfill(true)}
                className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
              >
                {isBackfilling ? "正在运行…" : "预演回填"}
              </button>
              <button
                type="button"
                disabled={isBackfilling}
                onClick={() => void runBackfill(false)}
                className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                执行回填
              </button>
            </div>
          </div>
        ) : null}
      </section>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
      {backfillResult ? (
        <BackfillResultPanel datasetId={datasetId || null} result={backfillResult} />
      ) : null}

      {isLoadingSnapshots ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          正在加载数据集快照…
        </section>
      ) : selectedSnapshot ? (
        <>
          <SnapshotList
            snapshots={snapshots}
            selectedSnapshotId={selectedSnapshot.id}
            onSelect={setSnapshotId}
          />
          <section className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <SnapshotDetails snapshot={selectedSnapshot} />
            <SnapshotDiff
              baseSnapshot={compareSnapshot}
              candidateSnapshot={selectedSnapshot}
              diff={diff}
            />
          </section>
        </>
      ) : (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          此数据集暂无快照。运行回填 CLI 或保存数据集以创建快照。
        </section>
      )}
    </div>
  );
}

function BackfillResultPanel({
  datasetId,
  result
}: {
  datasetId: string | null;
  result: EvaluationSnapshotBackfillResult;
}) {
  const detailRows = result.details.slice(0, 12);
  const report = buildEvaluationBackfillReport(result, datasetId);

  function download(format: "json" | "markdown") {
    const content =
      format === "json"
        ? `${JSON.stringify(report, null, 2)}\n`
        : renderEvaluationBackfillReportMarkdown(report);
    downloadText(
      content,
      backfillReportFilename(report, format === "json" ? "json" : "md"),
      format === "json" ? "application/json" : "text/markdown"
    );
  }

  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">回填结果</h2>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-md px-2 py-1 text-xs font-medium ${
              result.dry_run ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
            }`}
          >
            {result.dry_run ? "预演" : "applied"}
          </span>
          <button
            type="button"
            onClick={() => download("json")}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            导出 JSON
          </button>
          <button
            type="button"
            onClick={() => download("markdown")}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            导出 Markdown
          </button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <ResultMetric label="已扫描" value={result.scanned} />
        <ResultMetric label="已回填" value={result.backfilled} />
        <ResultMetric label="已跳过" value={result.skipped} />
        <ResultMetric label="新建快照" value={result.created_snapshots} />
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-slate-500">
              <th className="py-2 pr-4 font-medium">状态</th>
              <th className="py-2 pr-4 font-medium">数量</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(result.status_counts).map(([status, count]) => (
              <tr key={status} className="border-b border-border last:border-0">
                <td className="py-2 pr-4 font-mono text-xs text-slate-700">{status}</td>
                <td className="py-2 pr-4 text-slate-700">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detailRows.length > 0 ? (
        <>
          <h3 className="mt-5 text-sm font-semibold text-slate-950">详情</h3>
          <pre className="mt-3 max-h-[360px] overflow-auto rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
            <code>{JSON.stringify(detailRows, null, 2)}</code>
          </pre>
        </>
      ) : null}
    </section>
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

function ResultMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <span className="block text-xs font-medium uppercase text-slate-500">{label}</span>
      <span className="mt-1 block text-2xl font-semibold text-slate-950">{value}</span>
    </div>
  );
}

function SnapshotSelect({
  id,
  label,
  value,
  snapshots,
  disabled,
  onChange
}: {
  id: string;
  label: string;
  value: string;
  snapshots: EvaluationDatasetSnapshot[];
  disabled: boolean;
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
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500 disabled:bg-slate-100 disabled:text-slate-400"
      >
        {value === "" ? (
          <option value="">{snapshots.length === 0 ? "无快照" : "无对比"}</option>
        ) : null}
        {snapshots.map((snapshot) => (
          <option key={snapshot.id} value={snapshot.id}>
            v{snapshot.version} · {snapshot.id.slice(0, 8)} · {snapshot.cases_json.length} 个用例
          </option>
        ))}
      </select>
    </div>
  );
}

function SnapshotList({
  snapshots,
  selectedSnapshotId,
  onSelect
}: {
  snapshots: EvaluationDatasetSnapshot[];
  selectedSnapshotId: string;
  onSelect: (snapshotId: string) => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">快照版本</h2>
        <span className="text-sm text-slate-500">{snapshots.length} 个快照</span>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-slate-500">
              <th className="py-2 pr-4 font-medium">版本</th>
              <th className="py-2 pr-4 font-medium">快照</th>
              <th className="py-2 pr-4 font-medium">用例</th>
              <th className="py-2 pr-4 font-medium">基线</th>
              <th className="py-2 pr-4 font-medium">创建时间</th>
            </tr>
          </thead>
          <tbody>
            {snapshots.map((snapshot) => (
              <tr key={snapshot.id} className="border-b border-border last:border-0">
                <td className="py-3 pr-4 font-medium text-slate-950">v{snapshot.version}</td>
                <td className="py-3 pr-4">
                  <button
                    type="button"
                    onClick={() => onSelect(snapshot.id)}
                    className={`font-mono text-xs ${
                      selectedSnapshotId === snapshot.id
                        ? "font-semibold text-slate-950"
                        : "text-slate-600 hover:text-slate-950"
                    }`}
                  >
                    {snapshot.id}
                  </button>
                </td>
                <td className="py-3 pr-4">{snapshot.cases_json.length}</td>
                <td className="py-3 pr-4 font-mono text-xs text-slate-600">
                  {snapshot.baseline_run_id?.slice(0, 8) ?? "n/a"}
                </td>
                <td className="py-3 pr-4 text-slate-600">
                  {new Date(snapshot.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SnapshotDetails({ snapshot }: { snapshot: EvaluationDatasetSnapshot }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">快照详情</h2>
        <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
          v{snapshot.version}
        </span>
      </div>
      <div className="mt-4 overflow-hidden rounded-md border border-border">
        <table className="min-w-full text-left text-sm">
          <tbody>
            <DetailRow label="快照 ID" value={snapshot.id} />
            <DetailRow label="数据集 ID" value={snapshot.dataset_id} />
            <DetailRow label="任务类型" value={snapshot.task_type} />
            <DetailRow label="用例" value={snapshot.cases_json.length} />
            <DetailRow label="基线运行" value={snapshot.baseline_run_id ?? "未配置"} />
            <DetailRow label="创建时间" value={new Date(snapshot.created_at).toLocaleString()} />
          </tbody>
        </table>
      </div>
      <h3 className="mt-5 text-sm font-semibold text-slate-950">用例 JSON</h3>
      <pre className="mt-3 max-h-[620px] overflow-auto rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
        <code>{JSON.stringify(snapshot.cases_json, null, 2)}</code>
      </pre>
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value: unknown }) {
  return (
    <tr className="border-b border-border last:border-0">
      <th className="w-36 bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500">
        {label}
      </th>
      <td className="px-3 py-2 font-mono text-xs text-slate-700">{String(value)}</td>
    </tr>
  );
}

function SnapshotDiff({
  baseSnapshot,
  candidateSnapshot,
  diff
}: {
  baseSnapshot: EvaluationDatasetSnapshot | null;
  candidateSnapshot: EvaluationDatasetSnapshot;
  diff: CaseDiff | null;
}) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">版本差异</h2>
          <p className="mt-1 text-sm text-slate-500">
            {baseSnapshot
              ? `v${baseSnapshot.version} -> v${candidateSnapshot.version}`
              : "请选择另一快照进行对比。"}
          </p>
        </div>
      </div>
      {diff ? (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-4">
            <DiffCount label="新增" value={diff.counts.added} tone="emerald" />
            <DiffCount label="移除" value={diff.counts.removed} tone="red" />
            <DiffCount label="变更" value={diff.counts.changed} tone="amber" />
            <DiffCount label="未变更" value={diff.counts.unchanged} tone="slate" />
          </div>
          <div className="mt-4 max-h-[640px] overflow-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase text-slate-500">
                  <th className="py-2 pr-4 font-medium">用例</th>
                  <th className="py-2 pr-4 font-medium">状态</th>
                  <th className="py-2 pr-4 font-medium">基础版本</th>
                  <th className="py-2 pr-4 font-medium">快照</th>
                </tr>
              </thead>
              <tbody>
                {diff.items.map((item) => (
                  <tr key={item.key} className="border-b border-border last:border-0">
                    <td className="max-w-[220px] py-3 pr-4 font-mono text-xs text-slate-700">
                      {item.key}
                    </td>
                    <td className="py-3 pr-4">
                      <CaseStatusBadge status={item.status} />
                    </td>
                    <td className="max-w-[260px] py-3 pr-4 text-slate-600">
                      {caseSummary(item.base)}
                    </td>
                    <td className="max-w-[260px] py-3 pr-4 text-slate-600">
                      {caseSummary(item.candidate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="mt-4 text-sm text-slate-500">没有可用于对比的快照。</p>
      )}
    </section>
  );
}

function DiffCount({
  label,
  value,
  tone
}: {
  label: string;
  value: number;
  tone: "emerald" | "red" | "amber" | "slate";
}) {
  const tones = {
    emerald: "bg-emerald-50 text-emerald-700",
    red: "bg-red-50 text-red-700",
    amber: "bg-amber-50 text-amber-700",
    slate: "bg-slate-100 text-slate-700"
  };
  return (
    <div className={`rounded-md px-3 py-2 ${tones[tone]}`}>
      <span className="block text-xs font-medium uppercase">{label}</span>
      <span className="mt-1 block text-2xl font-semibold">{value}</span>
    </div>
  );
}

function CaseStatusBadge({ status }: { status: CaseDiffStatus }) {
  const className =
    status === "added"
      ? "bg-emerald-50 text-emerald-700"
      : status === "removed"
        ? "bg-red-50 text-red-700"
        : status === "changed"
          ? "bg-amber-50 text-amber-700"
          : "bg-slate-100 text-slate-600";
  return <span className={`rounded-md px-2 py-1 text-xs font-medium ${className}`}>{status}</span>;
}

function diffSnapshots(
  baseSnapshot: EvaluationDatasetSnapshot,
  candidateSnapshot: EvaluationDatasetSnapshot
): CaseDiff {
  const baseCases = caseMap(baseSnapshot);
  const candidateCases = caseMap(candidateSnapshot);
  const keys = Array.from(new Set([...baseCases.keys(), ...candidateCases.keys()])).sort();
  const counts: Record<CaseDiffStatus, number> = {
    added: 0,
    removed: 0,
    changed: 0,
    unchanged: 0
  };
  const items = keys.map((key) => {
    const base = baseCases.get(key) ?? null;
    const candidate = candidateCases.get(key) ?? null;
    const status = caseDiffStatus(base, candidate);
    counts[status] += 1;
    return { key, status, base, candidate };
  });
  return { counts, items };
}

function caseMap(snapshot: EvaluationDatasetSnapshot) {
  const seen = new Map<string, number>();
  const entries = snapshot.cases_json.map((item, index) => {
    const rawKey = caseKey(snapshot.task_type, item, index);
    const count = seen.get(rawKey) ?? 0;
    seen.set(rawKey, count + 1);
    const key = count === 0 ? rawKey : `${rawKey}#${count + 1}`;
    return [key, item] as const;
  });
  return new Map(entries);
}

function caseKey(taskType: EvaluationDatasetSnapshot["task_type"], item: Record<string, unknown>, index: number) {
  const caseId = stringValue(item.case_id);
  if (caseId) {
    return caseId;
  }
  const repoId = stringValue(item.repo_id) ?? "repo";
  if (taskType === "retrieval") {
    return [
      repoId,
      stringValue(item.expected_file) ?? "file",
      stringValue(item.question) ?? `case-${index + 1}`
    ].join("::");
  }
  return [repoId, stringValue(item.issue) ?? `case-${index + 1}`].join("::");
}

function caseDiffStatus(
  base: Record<string, unknown> | null,
  candidate: Record<string, unknown> | null
): CaseDiffStatus {
  if (base === null) {
    return "added";
  }
  if (candidate === null) {
    return "removed";
  }
  return stableStringify(base) === stableStringify(candidate) ? "unchanged" : "changed";
}

function caseSummary(item: Record<string, unknown> | null) {
  if (!item) {
    return "n/a";
  }
  const text =
    stringValue(item.question) ??
    stringValue(item.issue) ??
    stringValue(item.expected_file) ??
    stableStringify(item);
  return shortText(text, 140);
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function shortText(value: string, limit: number) {
  return value.length <= limit ? value : `${value.slice(0, Math.max(0, limit - 3))}...`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
