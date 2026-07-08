import type { TraceEvent } from "@/lib/types";
import { DiffViewer } from "@/components/diff/DiffViewer";
import { TestResultPanel } from "./TestResultPanel";
import { ToolCallCard } from "./ToolCallCard";

export function AgentTimeline({ events }: { events: TraceEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-white p-5 text-sm text-slate-500">
        No trace events yet.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {events.map((event, index) => (
        <article key={event.id} className="rounded-lg border border-border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase text-slate-500">Step {index + 1}</p>
              <h3 className="mt-1 text-sm font-semibold text-slate-950">
                {titleFor(event)}
              </h3>
            </div>
            <span className="text-xs text-slate-500">
              {new Date(event.created_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="mt-3">{bodyFor(event)}</div>
        </article>
      ))}
    </div>
  );
}

function titleFor(event: TraceEvent) {
  if (event.type === "tool_call") {
    return `Tool Call · ${event.tool_name ?? "unknown"}`;
  }
  if (event.type === "tool_result") {
    return `Tool Result · ${event.tool_name ?? "unknown"}`;
  }
  if (event.type === "patch") {
    return "Patch";
  }
  if (event.type === "test_result") {
    return "Test Result";
  }
  if (event.type === "reflection") {
    return "Reflection";
  }
  if (event.type === "final") {
    return "Final";
  }
  if (event.type === "error") {
    return "Error";
  }
  return "Plan";
}

function bodyFor(event: TraceEvent) {
  if (event.type === "patch") {
    return <DiffViewer diff={readDiff(event.output)} />;
  }
  if (event.type === "test_result") {
    return <TestResultPanel result={event.output} />;
  }
  if (event.type === "tool_call" || event.type === "tool_result") {
    return <ToolCallCard event={event} />;
  }
  return (
    <pre className="max-h-72 overflow-auto rounded bg-panel p-3 text-xs text-slate-700">
      <code>{JSON.stringify(event.output ?? event.input ?? {}, null, 2)}</code>
    </pre>
  );
}

function readDiff(value: unknown) {
  if (typeof value === "object" && value !== null && "diff" in value) {
    const diff = (value as { diff?: unknown }).diff;
    return typeof diff === "string" ? diff : "";
  }
  return "";
}
