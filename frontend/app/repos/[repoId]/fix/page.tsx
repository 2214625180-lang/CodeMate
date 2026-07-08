"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { AgentTimeline } from "@/components/agent/AgentTimeline";
import { TestResultPanel } from "@/components/agent/TestResultPanel";
import { DiffViewer } from "@/components/diff/DiffViewer";
import { API_BASE_URL, createFixRun, getRun, submitRunFeedback } from "@/lib/api";
import type { AgentRun, TraceEvent, TraceEventType } from "@/lib/types";

const TRACE_EVENTS: TraceEventType[] = [
  "plan",
  "tool_call",
  "tool_result",
  "patch",
  "test_result",
  "reflection",
  "final",
  "error"
];

export default function RepoFixPage() {
  const params = useParams<{ repoId: string }>();
  const repoId = params.repoId;
  const [issue, setIssue] = useState("");
  const [testCommand, setTestCommand] = useState("npm test");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const latestPatch = useMemo(() => {
    const patchEvent = [...events].reverse().find((event) => event.type === "patch");
    return readDiff(patchEvent?.output);
  }, [events]);

  const latestTest = useMemo(() => {
    return [...events].reverse().find((event) => event.type === "test_result")?.output ?? null;
  }, [events]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!issue.trim() || isRunning) {
      return;
    }

    setRun(null);
    setRunId(null);
    setEvents([]);
    setError(null);
    setIsRunning(true);

    try {
      const response = await createFixRun(repoId, issue, testCommand);
      setRunId(response.run_id);
      connectTrace(response.run_id);
    } catch (err) {
      setIsRunning(false);
      setError(err instanceof Error ? err.message : "Failed to start fix run");
    }
  }

  function connectTrace(nextRunId: string) {
    eventSourceRef.current?.close();
    const source = new EventSource(`${API_BASE_URL}/runs/${nextRunId}/trace`);
    eventSourceRef.current = source;

    for (const eventName of TRACE_EVENTS) {
      source.addEventListener(eventName, (message) => {
        const event = JSON.parse((message as MessageEvent).data) as TraceEvent;
        setEvents((current) => {
          if (current.some((item) => item.id === event.id)) {
            return current;
          }
          return [...current, event];
        });

        if (eventName === "final" || eventName === "error") {
          source.close();
          setIsRunning(false);
          void refreshRun(nextRunId);
        }
      });
    }

    source.onerror = () => {
      source.close();
      setIsRunning(false);
      void refreshRun(nextRunId);
    };
  }

  async function refreshRun(nextRunId: string) {
    try {
      const data = await getRun(nextRunId);
      setRun(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run");
    }
  }

  async function handleFeedback(status: "accepted" | "rejected" | "modified") {
    if (!runId) {
      return;
    }
    try {
      await submitRunFeedback(runId, status);
      await refreshRun(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit feedback");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/repos/${repoId}`} className="text-sm text-slate-600 hover:text-slate-950">
          Back to repository
        </Link>
        <h1 className="mt-3 text-2xl font-semibold text-slate-950">Bug Fix Agent</h1>
      </div>

      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
        <label htmlFor="issue" className="text-sm font-medium text-slate-700">
          Error log or failing test
        </label>
        <textarea
          id="issue"
          value={issue}
          onChange={(event) => setIssue(event.target.value)}
          placeholder="add function test fails: expected 5 but received -1"
          className="mt-2 min-h-36 w-full resize-y rounded-md border border-border px-3 py-2 text-sm outline-none focus:border-slate-500"
          required
        />
        <label htmlFor="test-command" className="mt-4 block text-sm font-medium text-slate-700">
          Test command
        </label>
        <input
          id="test-command"
          value={testCommand}
          onChange={(event) => setTestCommand(event.target.value)}
          className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
        />
        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-sm text-slate-500">
            {runId ? `Run ${runId}` : "No active run"}
          </p>
          <button
            type="submit"
            disabled={isRunning}
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isRunning ? "Running..." : "Start fix"}
          </button>
        </div>
      </form>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-slate-950">Agent Timeline</h2>
          <AgentTimeline events={events} />
        </div>
        <div className="space-y-4">
          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-950">Diff</h2>
            <DiffViewer diff={run?.final_diff || latestPatch} />
          </section>
          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-950">Tests</h2>
            <TestResultPanel result={run?.test_result ?? latestTest} />
          </section>
          {run ? (
            <section className="rounded-lg border border-border bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950">{run.status}</p>
                  <p className="mt-1 text-sm text-slate-600">{run.final_summary}</p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {(["accepted", "rejected", "modified"] as const).map((status) => (
                  <button
                    key={status}
                    type="button"
                    onClick={() => void handleFeedback(status)}
                    className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    {status}
                  </button>
                ))}
              </div>
              {run.feedback_status ? (
                <p className="mt-3 text-sm text-slate-500">Feedback: {run.feedback_status}</p>
              ) : null}
            </section>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function readDiff(value: unknown) {
  if (typeof value === "object" && value !== null && "diff" in value) {
    const diff = (value as { diff?: unknown }).diff;
    return typeof diff === "string" ? diff : "";
  }
  return "";
}
