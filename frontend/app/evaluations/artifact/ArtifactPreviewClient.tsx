"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getEvaluationRunArtifact } from "@/lib/api";
import { artifactFilename, renderEvaluationArtifactMarkdown } from "@/lib/evaluationArtifact";
import type { EvaluationRunArtifact } from "@/lib/types";

export function ArtifactPreviewClient({ runId }: { runId: string }) {
  const [artifact, setArtifact] = useState<EvaluationRunArtifact | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(runId));
  const [error, setError] = useState<string | null>(null);

  const markdown = useMemo(
    () => (artifact ? renderEvaluationArtifactMarkdown(artifact) : ""),
    [artifact]
  );

  const loadArtifact = useCallback(async () => {
    if (!runId) {
      setIsLoading(false);
      setError("缺少 runId 查询参数。");
      return;
    }
    try {
      const data = await getEvaluationRunArtifact(runId);
      setArtifact(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载评测产物失败");
    } finally {
      setIsLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void loadArtifact();
  }, [loadArtifact]);

  function download(format: "json" | "markdown") {
    if (!artifact) {
      return;
    }
    const content =
      format === "json" ? `${JSON.stringify(artifact, null, 2)}\n` : markdown;
    downloadText(
      content,
      artifactFilename(artifact, format === "json" ? "json" : "md"),
      format === "json" ? "application/json" : "text/markdown"
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">评测产物</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">
            {artifact?.run.name || artifact?.run.id || runId || "产物预览"}
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            根据已保存的评测运行产物生成的 Markdown 预览。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/evaluations"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            评测中心
          </Link>
          <button
            type="button"
            disabled={!artifact}
            onClick={() => download("json")}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
          >
            导出 JSON
          </button>
          <button
            type="button"
            disabled={!artifact}
            onClick={() => download("markdown")}
            className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            导出 Markdown
          </button>
        </div>
      </div>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      {isLoading ? (
        <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          正在加载产物…
        </section>
      ) : artifact ? (
        <section className="rounded-lg border border-border bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-slate-950">Markdown 报告</h2>
            <span className="text-xs text-slate-500">
              {artifact.run.task_type} · {artifact.run.status} · {artifact.cases.length} 个用例
            </span>
          </div>
          <pre className="mt-4 max-h-[760px] overflow-auto rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
            <code>{markdown}</code>
          </pre>
        </section>
      ) : null}
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
