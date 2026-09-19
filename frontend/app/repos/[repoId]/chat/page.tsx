"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useState } from "react";

import { CitationCard } from "@/components/chat/CitationCard";
import { backendApiUrl } from "@/lib/api";
import type { CodeCitation } from "@/lib/types";

type SseEvent =
  | { event: "token"; data: { content: string } }
  | { event: "citation"; data: CodeCitation }
  | { event: "done"; data: { citation_count: number; found: boolean } }
  | { event: "error"; data: { message: string } };

export default function RepoChatPage() {
  const params = useParams<{ repoId: string }>();
  const repoId = params.repoId;
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<CodeCitation[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming) {
      return;
    }

    setAnswer("");
    setCitations([]);
    setError(null);
    setIsStreaming(true);

    try {
      const response = await fetch(backendApiUrl(`/repos/${repoId}/chat`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed })
      });

      if (!response.ok || !response.body) {
        throw new Error(`问答请求失败，状态码：${response.status}`);
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
      setError(err instanceof Error ? err.message : "问答请求失败");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <Link href={`/repos/${repoId}`} className="text-sm text-slate-600 hover:text-slate-950">
            返回仓库
          </Link>
          <h1 className="mt-3 text-2xl font-semibold text-slate-950">代码问答</h1>
          <p className="mt-2 text-sm text-slate-600">
            针对已索引的仓库提问，回答以检索到的代码块和引用为依据。
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
        <label htmlFor="question" className="text-sm font-medium text-slate-700">
          问题
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="登录逻辑在哪里？"
          className="mt-2 min-h-28 w-full resize-y rounded-md border border-border px-3 py-2 text-sm outline-none focus:border-slate-500"
          required
        />
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={isStreaming}
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isStreaming ? "正在生成…" : "提问"}
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
            <CitationCard key={citation.chunk_id} repoId={repoId} citation={citation} />
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
  // POST chat carries a JSON body, so native EventSource is unsuitable. Parse
  // fetch incrementally and retain partial frames because network chunks do not
  // align with SSE message boundaries.
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
  // ChatService deliberately emits one JSON `data:` line per frame. If the
  // backend starts using multiline SSE data fields, this parser must evolve too.
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
