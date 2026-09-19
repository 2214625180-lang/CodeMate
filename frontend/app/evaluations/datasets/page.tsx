"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  createEvaluationDataset,
  deleteEvaluationDataset,
  listEvaluationRuns,
  listEvaluationDatasets,
  updateEvaluationDataset
} from "@/lib/api";
import type {
  EvaluationDataset,
  EvaluationDatasetPayload,
  EvaluationGatePolicy,
  EvaluationRun
} from "@/lib/types";

const DEFAULT_RETRIEVAL_CASES = `[
  {
    "repo_id": "replace-with-repo-id",
    "question": "Where is the add function implemented?",
    "expected_file": "src/math.js"
  }
]`;

const DEFAULT_FIX_CASES = `[
  {
    "repo_id": "replace-with-repo-id",
    "issue": "add function test fails: expected 5 but received -1",
    "test_command": "npm test",
    "expected_status": "verified_success",
    "expected_diff_contains": ["return a + b"]
  }
]`;

const DEFAULT_GATE_POLICY: EvaluationGatePolicy = {
  max_primary_metric_drop: 0,
  max_regressed_cases: 0,
  allow_incompatible: false,
  require_matching_dataset_snapshot: true,
  max_avg_latency_increase_sec: null,
  max_avg_tool_call_increase: null
};

export default function EvaluationDatasetsPage() {
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<EvaluationDataset | null>(null);
  const [filter, setFilter] = useState<"all" | "retrieval" | "fix">("all");
  const [taskType, setTaskType] = useState<"retrieval" | "fix">("retrieval");
  const [name, setName] = useState("检索基准评测");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState(1);
  const [baselineRunId, setBaselineRunId] = useState("");
  const [maxPrimaryMetricDropPercent, setMaxPrimaryMetricDropPercent] = useState(0);
  const [maxRegressedCases, setMaxRegressedCases] = useState(0);
  const [allowIncompatible, setAllowIncompatible] = useState(false);
  const [requireMatchingDatasetSnapshot, setRequireMatchingDatasetSnapshot] = useState(true);
  const [maxAvgLatencyIncreaseSec, setMaxAvgLatencyIncreaseSec] = useState("");
  const [maxAvgToolCallIncrease, setMaxAvgToolCallIncrease] = useState("");
  const [casesJson, setCasesJson] = useState(DEFAULT_RETRIEVAL_CASES);
  const [metadataJson, setMetadataJson] = useState("{}");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const visibleDatasets = useMemo(() => {
    if (filter === "all") {
      return datasets;
    }
    return datasets.filter((dataset) => dataset.task_type === filter);
  }, [datasets, filter]);

  const baselineOptions = useMemo(
    () =>
      runs.filter(
        (run) =>
          run.status === "completed" &&
          run.task_type === taskType &&
          selectedDataset !== null &&
          run.dataset_id === selectedDataset.id
      ),
    [runs, selectedDataset, taskType]
  );

  const loadDatasets = useCallback(async () => {
    try {
      const data = await listEvaluationDatasets();
      setDatasets(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载基准数据集失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  const loadRuns = useCallback(async () => {
    try {
      const data = await listEvaluationRuns(100);
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载评测记录失败");
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setNotice(null);

    try {
      const cases = parseCases(casesJson, taskType);
      const metadata = parseMetadata(metadataJson);
      const payload: EvaluationDatasetPayload = {
        name: name.trim(),
        task_type: taskType,
        description: description.trim() || null,
        version,
        baseline_run_id: baselineRunId || null,
        gate_policy_json: currentGatePolicy(),
        cases_json: cases,
        metadata_json: metadata
      };
      if (!payload.name) {
        throw new Error("请输入数据集名称。");
      }

      const saved = selectedDataset
        ? await updateEvaluationDataset(selectedDataset.id, updatePayload(selectedDataset, payload))
        : await createEvaluationDataset(payload);

      setSelectedDataset(saved);
      applyDatasetToForm(saved);
      setDatasets((current) => [saved, ...current.filter((dataset) => dataset.id !== saved.id)]);
      setNotice(selectedDataset ? "数据集已更新。" : "数据集已创建。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存基准数据集失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(dataset: EvaluationDataset) {
    if (!window.confirm(`删除数据集“${dataset.name}"?`)) {
      return;
    }

    setError(null);
    setNotice(null);
    try {
      await deleteEvaluationDataset(dataset.id);
      setDatasets((current) => current.filter((item) => item.id !== dataset.id));
      if (selectedDataset?.id === dataset.id) {
        startNew(dataset.task_type);
      }
      setNotice("数据集已删除。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除基准数据集失败");
    }
  }

  function startNew(nextTaskType: "retrieval" | "fix" = taskType) {
    setSelectedDataset(null);
    setTaskType(nextTaskType);
    setName(nextTaskType === "retrieval" ? "检索基准评测" : "修复基准评测");
    setDescription("");
    setVersion(1);
    setBaselineRunId("");
    applyGatePolicyToForm(DEFAULT_GATE_POLICY);
    setCasesJson(nextTaskType === "retrieval" ? DEFAULT_RETRIEVAL_CASES : DEFAULT_FIX_CASES);
    setMetadataJson("{}");
    setNotice(null);
  }

  function applyDatasetToForm(dataset: EvaluationDataset) {
    setTaskType(dataset.task_type);
    setName(dataset.name);
    setDescription(dataset.description ?? "");
    setVersion(dataset.version);
    setBaselineRunId(dataset.baseline_run_id ?? "");
    applyGatePolicyToForm(dataset.gate_policy_json ?? DEFAULT_GATE_POLICY);
    setCasesJson(JSON.stringify(dataset.cases_json, null, 2));
    setMetadataJson(JSON.stringify(dataset.metadata_json ?? {}, null, 2));
  }

  function selectDataset(dataset: EvaluationDataset) {
    setSelectedDataset(dataset);
    applyDatasetToForm(dataset);
    setNotice(null);
  }

  function switchTaskType(nextTaskType: "retrieval" | "fix") {
    setTaskType(nextTaskType);
    if (!selectedDataset) {
      setName(nextTaskType === "retrieval" ? "检索基准评测" : "修复基准评测");
      setCasesJson(nextTaskType === "retrieval" ? DEFAULT_RETRIEVAL_CASES : DEFAULT_FIX_CASES);
      setBaselineRunId("");
    }
  }

  function currentGatePolicy(): EvaluationGatePolicy {
    return {
      max_primary_metric_drop: Math.max(0, maxPrimaryMetricDropPercent) / 100,
      max_regressed_cases: Math.max(0, Math.trunc(maxRegressedCases)),
      allow_incompatible: allowIncompatible,
      require_matching_dataset_snapshot: requireMatchingDatasetSnapshot,
      max_avg_latency_increase_sec: optionalNumber(maxAvgLatencyIncreaseSec),
      max_avg_tool_call_increase: optionalNumber(maxAvgToolCallIncrease)
    };
  }

  function applyGatePolicyToForm(policy: EvaluationGatePolicy) {
    const normalized = { ...DEFAULT_GATE_POLICY, ...policy };
    setMaxPrimaryMetricDropPercent(Math.round(normalized.max_primary_metric_drop * 1000) / 10);
    setMaxRegressedCases(normalized.max_regressed_cases);
    setAllowIncompatible(normalized.allow_incompatible);
    setRequireMatchingDatasetSnapshot(normalized.require_matching_dataset_snapshot);
    setMaxAvgLatencyIncreaseSec(
      normalized.max_avg_latency_increase_sec === null
        ? ""
        : String(normalized.max_avg_latency_increase_sec)
    );
    setMaxAvgToolCallIncrease(
      normalized.max_avg_tool_call_increase === null
        ? ""
        : String(normalized.max_avg_tool_call_increase)
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">评测中心</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">基准数据集</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            管理可复用的检索与代码修复基准用例、版本和元数据。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/evaluations/datasets/snapshots"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            快照
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

      <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex rounded-md border border-border bg-white p-1">
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
            <button
              type="button"
              onClick={() => startNew(taskType)}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              新建数据集
            </button>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_120px]">
            <div>
              <label htmlFor="dataset-name" className="text-sm font-medium text-slate-700">
                数据集名称
              </label>
              <input
                id="dataset-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
              />
            </div>
            <div>
              <label htmlFor="dataset-version" className="text-sm font-medium text-slate-700">
                版本
              </label>
              <input
                id="dataset-version"
                type="number"
                min={1}
                value={version}
                onChange={(event) => setVersion(Number(event.target.value))}
                className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
              />
            </div>
          </div>

          <label htmlFor="dataset-description" className="mt-4 block text-sm font-medium text-slate-700">
            说明
          </label>
          <textarea
            id="dataset-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="mt-2 min-h-20 w-full resize-y rounded-md border border-border px-3 py-2 text-sm outline-none focus:border-slate-500"
          />

          <div className="mt-5 border-t border-border pt-4">
            <h2 className="text-sm font-semibold text-slate-950">回归门禁策略</h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label htmlFor="baseline-run" className="text-sm font-medium text-slate-700">
                  基线运行
                </label>
                <select
                  id="baseline-run"
                  value={baselineRunId}
                  disabled={!selectedDataset}
                  onChange={(event) => setBaselineRunId(event.target.value)}
                  className="mt-2 min-h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500 disabled:bg-slate-100 disabled:text-slate-400"
                >
                  <option value="">
                    {selectedDataset ? "无基线" : "请先保存数据集，再选择基线"}
                  </option>
                  {baselineOptions.map((run) => (
                    <option key={run.id} value={run.id}>
                      {run.name || run.id} · {new Date(run.created_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="primary-drop" className="text-sm font-medium text-slate-700">
                  最大指标降幅（%）
                </label>
                <input
                  id="primary-drop"
                  type="number"
                  min={0}
                  max={100}
                  step={0.1}
                  value={maxPrimaryMetricDropPercent}
                  onChange={(event) => setMaxPrimaryMetricDropPercent(Number(event.target.value))}
                  className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
                />
              </div>

              <div>
                <label htmlFor="regressed-cases" className="text-sm font-medium text-slate-700">
                  最多退化用例数
                </label>
                <input
                  id="regressed-cases"
                  type="number"
                  min={0}
                  value={maxRegressedCases}
                  onChange={(event) => setMaxRegressedCases(Number(event.target.value))}
                  className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
                />
              </div>

              <div>
                <label htmlFor="latency-increase" className="text-sm font-medium text-slate-700">
                  最大耗时增量（秒）
                </label>
                <input
                  id="latency-increase"
                  type="number"
                  min={0}
                  step={0.001}
                  value={maxAvgLatencyIncreaseSec}
                  onChange={(event) => setMaxAvgLatencyIncreaseSec(event.target.value)}
                  className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
                  placeholder="optional"
                />
              </div>

              <div>
                <label htmlFor="tool-call-increase" className="text-sm font-medium text-slate-700">
                  最大工具调用次数增量
                </label>
                <input
                  id="tool-call-increase"
                  type="number"
                  min={0}
                  step={0.1}
                  value={maxAvgToolCallIncrease}
                  onChange={(event) => setMaxAvgToolCallIncrease(event.target.value)}
                  className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
                  placeholder="optional"
                />
              </div>

              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={allowIncompatible}
                  onChange={(event) => setAllowIncompatible(event.target.checked)}
                  className="h-4 w-4 rounded border-border"
                />
                允许不兼容的对比
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={requireMatchingDatasetSnapshot}
                  onChange={(event) => setRequireMatchingDatasetSnapshot(event.target.checked)}
                  className="h-4 w-4 rounded border-border"
                />
                要求快照一致
              </label>
            </div>
          </div>

          <label htmlFor="dataset-cases" className="mt-4 block text-sm font-medium text-slate-700">
            用例 JSON
          </label>
          <textarea
            id="dataset-cases"
            value={casesJson}
            onChange={(event) => setCasesJson(event.target.value)}
            className="mt-2 min-h-[360px] w-full resize-y rounded-md border border-border px-3 py-2 font-mono text-xs outline-none focus:border-slate-500"
            spellCheck={false}
          />

          <label htmlFor="dataset-metadata" className="mt-4 block text-sm font-medium text-slate-700">
            元数据 JSON
          </label>
          <textarea
            id="dataset-metadata"
            value={metadataJson}
            onChange={(event) => setMetadataJson(event.target.value)}
            className="mt-2 min-h-28 w-full resize-y rounded-md border border-border px-3 py-2 font-mono text-xs outline-none focus:border-slate-500"
            spellCheck={false}
          />

          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-xs text-slate-500">
              {selectedDataset ? `正在编辑 ${selectedDataset.id}` : "新建数据集"}
            </p>
            <button
              type="submit"
              disabled={isSaving}
              className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isSaving ? "正在保存…" : selectedDataset ? "保存修改" : "创建数据集"}
            </button>
          </div>
        </form>

        <div className="space-y-4">
          {error ? (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
          ) : null}
          {notice ? (
            <div className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div>
          ) : null}

          <section className="rounded-lg border border-border bg-white p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">数据集</h2>
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value as "all" | "retrieval" | "fix")}
                className="min-h-9 rounded-md border border-border px-2 text-sm outline-none focus:border-slate-500"
              >
                <option value="all">全部</option>
                <option value="retrieval">检索</option>
                <option value="fix">修复</option>
              </select>
            </div>

            {isLoading ? (
              <p className="mt-4 text-sm text-slate-500">正在加载数据集…</p>
            ) : visibleDatasets.length === 0 ? (
              <p className="mt-4 text-sm text-slate-500">暂无基准数据集。</p>
            ) : (
              <div className="mt-4 space-y-2">
                {visibleDatasets.map((dataset) => (
                  <div
                    key={dataset.id}
                    className={`rounded-md border p-3 ${
                      selectedDataset?.id === dataset.id
                        ? "border-slate-400 bg-slate-50"
                        : "border-border bg-white"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => selectDataset(dataset)}
                      className="block w-full text-left"
                    >
                      <span className="block font-medium text-slate-950">{dataset.name}</span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {dataset.task_type} · v{dataset.version} · {dataset.cases_json.length} 个用例
                      </span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {dataset.baseline_run_id
                          ? `基线 ${dataset.baseline_run_id.slice(0, 8)}`
                          : "未设置回归门禁基线"}
                      </span>
                      {dataset.description ? (
                        <span className="mt-2 block text-xs text-slate-600">
                          {dataset.description}
                        </span>
                      ) : null}
                    </button>
                    <div className="mt-3 flex items-center justify-between gap-2 text-xs text-slate-500">
                      <span>{new Date(dataset.updated_at).toLocaleString()}</span>
                      <div className="flex items-center gap-3">
                        <Link
                          href={`/evaluations/history?datasetId=${dataset.id}`}
                          className="font-medium text-slate-700 hover:text-slate-950"
                        >
                          历史记录
                        </Link>
                        <Link
                          href={`/evaluations/datasets/snapshots?datasetId=${dataset.id}`}
                          className="font-medium text-slate-700 hover:text-slate-950"
                        >
                          快照
                        </Link>
                        <button
                          type="button"
                          onClick={() => void handleDelete(dataset)}
                          className="font-medium text-red-600 hover:text-red-700"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}

function updatePayload(
  original: EvaluationDataset,
  next: EvaluationDatasetPayload
): Partial<EvaluationDatasetPayload> {
  const payload: Partial<EvaluationDatasetPayload> = {
    name: next.name,
    task_type: next.task_type,
    description: next.description,
    baseline_run_id: next.baseline_run_id,
    gate_policy_json: next.gate_policy_json,
    metadata_json: next.metadata_json
  };

  if (JSON.stringify(original.cases_json) !== JSON.stringify(next.cases_json)) {
    payload.cases_json = next.cases_json;
  }
  if (original.version !== next.version) {
    payload.version = next.version;
  }

  return payload;
}

function optionalNumber(value: string) {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  if (Number.isNaN(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

function parseCases(raw: string, taskType: "retrieval" | "fix"): Record<string, unknown>[] {
  const parsed = JSON.parse(raw) as unknown;
  const cases = Array.isArray(parsed)
    ? parsed
    : isRecord(parsed) && Array.isArray(parsed[taskType])
      ? parsed[taskType]
      : null;

  if (!cases || cases.length === 0) {
    throw new Error(`用例 JSON 必须是数组，或包含以下字段的对象：${taskType}[].`);
  }

  return cases.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`用例 ${index + 1} 必须是对象。`);
    }

    if (taskType === "retrieval") {
      requireString(item, "repo_id", index);
      requireString(item, "question", index);
      requireString(item, "expected_file", index);
    } else {
      requireString(item, "repo_id", index);
      requireString(item, "issue", index);
      const rawExpectedStatus = stringValue(item.expected_status);
      const expectedStatus = rawExpectedStatus === "success"
        ? "verified_success"
        : rawExpectedStatus ?? "verified_success";
      if (!isFixExpectedStatus(expectedStatus)) {
        throw new Error(
          `用例 ${index + 1} 的 expected_status 必须是严格验证状态。`
        );
      }
      item.expected_status = expectedStatus;
    }

    return item;
  });
}

function parseMetadata(raw: string): Record<string, unknown> {
  const parsed = JSON.parse(raw) as unknown;
  if (!isRecord(parsed)) {
    throw new Error("元数据 JSON 必须是对象。");
  }
  return parsed;
}

function requireString(item: Record<string, unknown>, key: string, index: number) {
  if (!stringValue(item[key])) {
    throw new Error(`用例 ${index + 1} 必须包含 ${key}.`);
  }
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isFixExpectedStatus(value: string) {
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
