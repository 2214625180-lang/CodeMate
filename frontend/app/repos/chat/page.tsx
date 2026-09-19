"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { CitationCard } from "@/components/chat/CitationCard";
import { backendApiUrl, listRepositories } from "@/lib/api";
import type { CodeCitation, Repository } from "@/lib/types";

type SseEvent =
  | { event: "token"; data: { content: string } }
  | { event: "citation"; data: CodeCitation }
  | { event: "done"; data: { citation_count: number; found: boolean; repo_count?: number } }
  | { event: "error"; data: { message: string } };

export default function MultiRepoChatPage() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<CodeCitation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const indexedRepositories = useMemo(
    () => repositories.filter((repository) => repository.status === "indexed"),
    [repositories]
  );

  const loadRepositories = useCallback(async () => {
    try {
      const data = await listRepositories();
      setRepositories(data);
      setSelectedRepoIds((current) => {
        const indexedIds = data
          .filter((repository) => repository.status === "indexed")
          .map((repository) => repository.id);
        const kept = current.filter((repoId) => indexedIds.includes(repoId));
        return kept.length > 0 ? kept : indexedIds;
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载仓库列表失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRepositories();
  }, [loadRepositories]);

  function toggleRepository(repoId: string) {
    setSelectedRepoIds((current) =>
      current.includes(repoId)
        ? current.filter((selectedId) => selectedId !== repoId)
        : [...current, repoId]
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming || selectedRepoIds.length === 0) {
      return;
    }

    setAnswer("");
    setCitations([]);
    setError(null);
    setIsStreaming(true);

    try {
      const response = await fetch(backendApiUrl("/repos/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, repo_ids: selectedRepoIds })
      });

      if (!response.ok || !response.body) {
        throw new Error(`跨仓库问答请求失败，状态码：${response.status}`);
      }

      await readSse(response.body, (message) => {
        if (message.event === "token") {
          setAnswer((current) => current + message.data.content);
        } else if (message.event === "citation") {
          setCitations((current) => [...current, message.data]);
        } else if (message.event === "error") {
          setError(message.data.message);
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "跨仓库问答请求失败");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/repos" className="text-sm text-slate-600 hover:text-slate-950">
          返回仓库列表
        </Link>
        <h1 className="mt-3 text-2xl font-semibold text-slate-950">跨仓库问答</h1>
        <p className="mt-2 text-sm text-slate-600">
          同时向多个已索引仓库提问，代码引用会标明来源仓库。
        </p>
      </div>

      <section className="rounded-lg border border-border bg-white p-5">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-950">仓库</h2>
          <button
            type="button"
            onClick={() => setSelectedRepoIds(indexedRepositories.map((repository) => repository.id))}
            disabled={indexedRepositories.length === 0}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
          >
            选择全部已索引仓库
          </button>
        </div>

        {isLoading ? (
          <p className="mt-4 text-sm text-slate-500">正在加载仓库列表…</p>
        ) : indexedRepositories.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">暂无可用的已索引仓库。</p>
        ) : (
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {indexedRepositories.map((repository) => (
              <label
                key={repository.id}
                className="flex min-w-0 items-start gap-3 rounded-md border border-border p-3"
              >
                <input
                  type="checkbox"
                  checked={selectedRepoIds.includes(repository.id)}
                  onChange={() => toggleRepository(repository.id)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-slate-950">
                    {repository.name}
                  </span>
                  <span className="block truncate text-xs text-slate-500">
                    {repository.file_count} 个文件， {repository.chunk_count} 个代码块
                  </span>
                </span>
              </label>
            ))}
          </div>
        )}
      </section>

      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
        <label htmlFor="question" className="text-sm font-medium text-slate-700">
          问题
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="这些仓库里认证和权限逻辑分别在哪里？"
          className="mt-2 min-h-28 w-full resize-y rounded-md border border-border px-3 py-2 text-sm outline-none focus:border-slate-500"
          required
        />
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={isStreaming || selectedRepoIds.length === 0}
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isStreaming ? "正在生成…" : "跨仓库提问"}
          </button>
        </div>
      </form>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      <section className="rounded-lg border border-border bg-white p-5">
        <h2 className="text-lg font-semibold text-slate-950">回答</h2>
        <div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-700">
          {answer || (isStreaming ? "正在等待回答…" : "暂无回答。")}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-slate-950">代码引用</h2>
        {citations.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-white p-5 text-sm text-slate-500">
            暂无引用。
          </div>
        ) : (
          citations.map((citation) => (
            <CitationCard
              key={`${citation.repo_id ?? "repo"}-${citation.chunk_id}`}
              citation={citation}
            />
          ))
        )}
      </section>
    </div>
  );
}

async function readSse(
  body: ReadableStream<Uint8Array>,
  onMessage: (message: SseEvent) => void
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const parsed = parseSseEvent(part);
      if (parsed) {
        onMessage(parsed);
      }
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseEvent(buffer);
    if (parsed) {
      onMessage(parsed);
    }
  }
}

function parseSseEvent(raw: string): SseEvent | null {
  const eventLine = raw.split("\n").find((line) => line.startsWith("event:"));
  const dataLine = raw.split("\n").find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) {
    return null;
  }

  const event = eventLine.slice("event:".length).trim();
  const data = JSON.parse(dataLine.slice("data:".length).trim());
  if (event === "token" || event === "citation" || event === "done" || event === "error") {
    return { event, data } as SseEvent;
  }
  return null;
}
