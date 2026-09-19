"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import {
  getRepoMemory,
  getRepository,
  getRepositoryStatus,
  inspectCI,
  refreshRepoMemory,
  reindexRepository,
  writeCIWorkflow
} from "@/lib/api";
import type { CIConfig, RepoMemory, Repository, RepositoryStatusResponse } from "@/lib/types";

export default function RepoDetailPage() {
  const params = useParams<{ repoId: string }>();
  const repoId = params.repoId;
  const [repository, setRepository] = useState<Repository | null>(null);
  const [status, setStatus] = useState<RepositoryStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [insightError, setInsightError] = useState<string | null>(null);
  const [memory, setMemory] = useState<RepoMemory | null>(null);
  const [ciConfig, setCIConfig] = useState<CIConfig | null>(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [isRefreshingMemory, setIsRefreshingMemory] = useState(false);
  const [isWritingCI, setIsWritingCI] = useState(false);

  const languageEntries = useMemo(() => {
    if (!repository) {
      return [];
    }
    return Object.entries(repository.language_summary);
  }, [repository]);

  const loadRepository = useCallback(async () => {
    try {
      const [repo, repoStatus] = await Promise.all([
        getRepository(repoId),
        getRepositoryStatus(repoId)
      ]);
      setRepository(repo);
      setStatus(repoStatus);
      if (repoStatus.status !== "indexed") {
        setMemory(null);
        setCIConfig(null);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载仓库失败");
    }
  }, [repoId]);

  const loadInsights = useCallback(async () => {
    // Memory and CI are independent projections of an indexed repository. One
    // failed endpoint should not discard the other endpoint's usable result.
    const [memoryResult, ciResult] = await Promise.allSettled([
      getRepoMemory(repoId),
      inspectCI(repoId)
    ]);

    const failures: string[] = [];
    if (memoryResult.status === "fulfilled") {
      setMemory(memoryResult.value);
    } else {
      failures.push("memory");
    }

    if (ciResult.status === "fulfilled") {
      setCIConfig(ciResult.value);
    } else {
      failures.push("CI");
    }

    setInsightError(
      failures.length > 0 ? `加载失败：${failures.join(" 和 ")} 数据` : null
    );
  }, [repoId]);

  useEffect(() => {
    // Status polling owns indexing progress. Insights are fetched by the next
    // effect only after both the status and indexed_at prove an index exists.
    void loadRepository();
    const interval = window.setInterval(() => {
      void loadRepository();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [loadRepository]);

  useEffect(() => {
    if (status?.status !== "indexed" || !repository?.indexed_at) {
      return;
    }
    void loadInsights();
  }, [loadInsights, repository?.indexed_at, status?.status]);

  async function handleReindex() {
    setIsReindexing(true);
    setError(null);
    try {
      const repo = await reindexRepository(repoId);
      setRepository(repo);
      setMemory(null);
      setCIConfig(null);
      await loadRepository();
    } catch (err) {
      setError(err instanceof Error ? err.message : "触发重新索引失败");
    } finally {
      setIsReindexing(false);
    }
  }

  async function handleRefreshMemory() {
    setIsRefreshingMemory(true);
    setInsightError(null);
    try {
      const nextMemory = await refreshRepoMemory(repoId);
      setMemory(nextMemory);
    } catch (err) {
      setInsightError(err instanceof Error ? err.message : "刷新仓库记忆失败");
    } finally {
      setIsRefreshingMemory(false);
    }
  }

  async function handleWriteCIWorkflow() {
    setIsWritingCI(true);
    setInsightError(null);
    try {
      const nextConfig = await writeCIWorkflow(repoId);
      setCIConfig(nextConfig);
    } catch (err) {
      setInsightError(err instanceof Error ? err.message : "写入 CI 工作流失败");
    } finally {
      setIsWritingCI(false);
    }
  }

  if (error) {
    return <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>;
  }

  if (!repository || !status) {
    return (
      <div className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
        正在加载仓库…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link href="/repos" className="text-sm text-slate-600 hover:text-slate-950">
        返回仓库列表
      </Link>

      <section className="rounded-lg border border-border bg-white p-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <h1 className="text-2xl font-semibold text-slate-950">{repository.name}</h1>
            <p className="mt-2 max-w-3xl break-all text-sm text-slate-600">
              {repository.repo_url}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={status.status} />
            <Link
              href={`/repos/${repoId}/chat`}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              问答
            </Link>
            <Link
              href={`/repos/${repoId}/fix`}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              修复
            </Link>
            <Link
              href={`/repos/${repoId}/review`}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              代码审查
            </Link>
            <button
              type="button"
              onClick={handleReindex}
              disabled={isReindexing}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
            >
              {isReindexing ? "已入队…" : "增量重新索引"}
            </button>
          </div>
        </div>

        {repository.error_message ? (
          <div className="mt-5 rounded-md bg-red-50 p-3 text-sm text-red-700">
            {repository.error_message}
          </div>
        ) : null}

        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Metric label="源文件" value={String(status.file_count)} />
          <Metric label="代码块" value={String(status.chunk_count)} />
          <Metric label="提交" value={repository.last_commit_hash?.slice(0, 12) ?? "n/a"} />
          <Metric
            label="索引时间"
            value={repository.indexed_at ? new Date(repository.indexed_at).toLocaleString() : "n/a"}
          />
          <Metric
            label="工作区"
            value={repository.status === "indexed" ? "ready" : repository.status}
          />
        </div>
      </section>

      {insightError ? (
        <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">{insightError}</div>
      ) : null}

      <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,0.9fr)]">
        <RepoMemoryPanel
          memory={memory}
          isIndexed={status.status === "indexed"}
          isRefreshing={isRefreshingMemory}
          onRefresh={handleRefreshMemory}
        />
        <CIPanel
          config={ciConfig}
          isIndexed={status.status === "indexed"}
          isWriting={isWritingCI}
          onWrite={handleWriteCIWorkflow}
        />
      </section>

      <section className="rounded-lg border border-border bg-white p-6">
        <h2 className="text-lg font-semibold text-slate-950">语言分布</h2>
        {languageEntries.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">暂无已扫描的源文件。</p>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {languageEntries.map(([language, count]) => (
              <div key={language} className="rounded-md border border-border p-3">
                <p className="text-sm font-medium text-slate-950">{language}</p>
                <p className="mt-1 text-2xl font-semibold text-slate-800">{count}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function RepoMemoryPanel({
  memory,
  isIndexed,
  isRefreshing,
  onRefresh
}: {
  memory: RepoMemory | null;
  isIndexed: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  const modules = memory?.data.modules ?? [];
  const keyFiles = memory?.data.key_files ?? [];
  const symbols = memory?.data.symbols ?? [];
  const frameworks = memory?.data.dependencies?.frameworks ?? [];
  const dependencies = memory?.data.dependencies?.dependencies ?? [];
  const stackDependencies = [
    ...frameworks,
    ...dependencies.filter((dependency) => !frameworks.includes(dependency))
  ].slice(0, 8);

  return (
    <section className="rounded-lg border border-border bg-white p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">仓库记忆</h2>
          <p className="mt-1 text-xs text-slate-500">
            {memory?.updated_at ? new Date(memory.updated_at).toLocaleString() : "尚未刷新"}
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={!isIndexed || isRefreshing}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
        >
          {isRefreshing ? "正在刷新…" : "刷新"}
        </button>
      </div>

      {!isIndexed ? (
        <p className="mt-4 text-sm text-slate-500">索引完成后可用。</p>
      ) : memory ? (
        <div className="mt-5 space-y-5">
          <p className="text-sm leading-6 text-slate-700">{memory.summary ?? "暂无摘要。"}</p>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">模块</h3>
            {modules.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">暂无模块数据。</p>
            ) : (
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {modules.slice(0, 8).map((module) => (
                  <div key={module.path} className="rounded-md border border-border p-3">
                    <p className="truncate font-mono text-xs text-slate-700">{module.path}</p>
                    <p className="mt-1 text-xs text-slate-500">{module.file_count} 个文件</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">技术栈</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {stackDependencies.map((dependency) => (
                <span
                  key={dependency}
                  className="rounded bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700"
                >
                  {dependency}
                </span>
              ))}
              {stackDependencies.length === 0 ? (
                <span className="text-sm text-slate-500">暂无依赖数据。</span>
              ) : null}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">关键文件</h3>
            {keyFiles.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">未检测到关键文件。</p>
            ) : (
              <ul className="mt-2 divide-y divide-border border-y border-border">
                {keyFiles.slice(0, 6).map((file) => (
                  <li key={file.path} className="flex items-center justify-between gap-3 py-2">
                    <span className="min-w-0 truncate font-mono text-xs text-slate-700">
                      {file.path}
                    </span>
                    <span className="shrink-0 text-xs text-slate-500">{file.language}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">符号</h3>
            {symbols.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">暂无符号记忆。</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {symbols.slice(0, 6).map((symbol) => (
                  <li key={`${symbol.path}-${symbol.name}`} className="text-xs text-slate-700">
                    <span className="font-medium text-slate-900">{symbol.name}</span>
                    <span className="ml-2 font-mono text-slate-500">{symbol.path}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-500">正在加载仓库记忆…</p>
      )}
    </section>
  );
}

function CIPanel({
  config,
  isIndexed,
  isWriting,
  onWrite
}: {
  config: CIConfig | null;
  isIndexed: boolean;
  isWriting: boolean;
  onWrite: () => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-white p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">CI</h2>
          <p className="mt-1 text-xs text-slate-500">
            {config?.workflow_path ?? "尚未生成工作流"}
          </p>
        </div>
        <button
          type="button"
          onClick={onWrite}
          disabled={!isIndexed || !config || isWriting}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
        >
          {isWriting ? "正在写入…" : "写入工作流"}
        </button>
      </div>

      {!isIndexed ? (
        <p className="mt-4 text-sm text-slate-500">索引完成后可用。</p>
      ) : config ? (
        <div className="mt-5 space-y-5">
          {config.applied_path ? (
            <div className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
              已写入 {config.applied_path}
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <Metric label="技术生态" value={config.ecosystem.join(", ")} />
            <Metric label="包管理器" value={config.package_manager ?? "n/a"} />
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">已检测到的 CI</h3>
            {config.detected_configs.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">暂无 CI 配置。</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {config.detected_configs.map((path) => (
                  <li key={path} className="font-mono text-xs text-slate-700">
                    {path}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">测试命令</h3>
            <ul className="mt-2 space-y-1">
              {config.test_commands.map((command) => (
                <li key={command} className="font-mono text-xs text-slate-700">
                  {command}
                </li>
              ))}
            </ul>
          </div>

          <pre className="max-h-80 overflow-auto rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
            {config.workflow_yaml}
          </pre>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-500">正在加载 CI 数据…</p>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-panel p-3">
      <p className="text-xs uppercase text-slate-500">{label}</p>
      <p className="mt-2 truncate text-sm font-medium text-slate-900">{value}</p>
    </div>
  );
}
