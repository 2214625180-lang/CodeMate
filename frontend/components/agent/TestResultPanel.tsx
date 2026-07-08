export function TestResultPanel({ result }: { result: unknown }) {
  const data = isRecord(result) ? result : {};
  const passed = Boolean(data.passed);
  return (
    <div className="rounded-md border border-border bg-white p-4">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold text-slate-950">Test Result</h3>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            passed ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
          }`}
        >
          {passed ? "passed" : "failed"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
        <span>command: {String(data.command ?? "n/a")}</span>
        <span>exit: {String(data.exit_code ?? "n/a")}</span>
        <span>ran: {String(data.tests_ran ?? false)}</span>
      </div>
      <pre className="mt-3 max-h-72 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-100">
        <code>{[data.stdout, data.stderr].filter(Boolean).join("\n") || "(no output)"}</code>
      </pre>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
