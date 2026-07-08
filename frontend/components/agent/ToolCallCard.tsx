import type { TraceEvent } from "@/lib/types";

export function ToolCallCard({ event }: { event: TraceEvent }) {
  return (
    <div className="rounded-md border border-border bg-panel p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-950">
          {event.tool_name ?? event.type}
        </p>
        {event.duration_ms !== null ? (
          <span className="text-xs text-slate-500">{event.duration_ms}ms</span>
        ) : null}
      </div>
      <pre className="mt-3 max-h-72 overflow-auto rounded bg-white p-3 text-xs text-slate-700">
        <code>{formatJson(event.output ?? event.input)}</code>
      </pre>
    </div>
  );
}

function formatJson(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value ?? {}, null, 2);
}
