import type { MCPToolApproval, MCPToolExecution, TraceEvent } from "@/lib/types";
import { DiffViewer } from "@/components/diff/DiffViewer";
import { TestResultPanel } from "./TestResultPanel";
import { ToolCallCard } from "./ToolCallCard";

export function AgentTimeline({
  events,
  approvalOverrides = {},
  decidingApprovalId,
  onApprovalDecision,
  executionOverrides = {},
  reconcilingExecutionId,
  onExecutionReconcile
}: {
  events: TraceEvent[];
  approvalOverrides?: Record<string, MCPToolApproval>;
  decidingApprovalId?: string | null;
  onApprovalDecision?: (
    approval: MCPToolApproval,
    decision: "approve" | "reject"
  ) => void;
  executionOverrides?: Record<string, MCPToolExecution>;
  reconcilingExecutionId?: string | null;
  onExecutionReconcile?: (
    execution: MCPToolExecution,
    action: "confirm_succeeded" | "confirm_failed" | "retry"
  ) => void;
}) {
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
          <div className="mt-3">
            {bodyFor(
              event,
              approvalOverrides,
              decidingApprovalId,
              onApprovalDecision,
              executionOverrides,
              reconcilingExecutionId,
              onExecutionReconcile
            )}
          </div>
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
  if (event.type === "observation") {
    return `Observation · ${event.tool_name ?? "agent"}`;
  }
  if (event.type === "approval_required") {
    return `Approval Required · ${event.tool_name ?? "MCP tool"}`;
  }
  if (event.type === "approval_decision") {
    return `Approval Decision · ${event.tool_name ?? "MCP tool"}`;
  }
  if (event.type === "mcp_execution") {
    return `MCP Execution · ${event.tool_name ?? "MCP tool"}`;
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

function bodyFor(
  event: TraceEvent,
  approvalOverrides: Record<string, MCPToolApproval>,
  decidingApprovalId?: string | null,
  onApprovalDecision?: (
    approval: MCPToolApproval,
    decision: "approve" | "reject"
  ) => void,
  executionOverrides: Record<string, MCPToolExecution> = {},
  reconcilingExecutionId?: string | null,
  onExecutionReconcile?: (
    execution: MCPToolExecution,
    action: "confirm_succeeded" | "confirm_failed" | "retry"
  ) => void
) {
  if (event.type === "approval_required") {
    const original = readApproval(event.output);
    if (original) {
      const approval = approvalOverrides[original.id] ?? original;
      return (
        <ApprovalCard
          approval={approval}
          deciding={decidingApprovalId === approval.id}
          onDecision={onApprovalDecision}
        />
      );
    }
  }
  if (event.type === "mcp_execution") {
    const original = readExecution(event.output);
    if (original) {
      const execution = executionOverrides[original.id] ?? original;
      return (
        <ExecutionCard
          execution={execution}
          reconciling={reconcilingExecutionId === execution.id}
          onReconcile={onExecutionReconcile}
        />
      );
    }
  }
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

function ExecutionCard({
  execution,
  reconciling,
  onReconcile
}: {
  execution: MCPToolExecution;
  reconciling: boolean;
  onReconcile?: (
    execution: MCPToolExecution,
    action: "confirm_succeeded" | "confirm_failed" | "retry"
  ) => void;
}) {
  const unknown = execution.status === "unknown";
  return (
    <div className="space-y-3 rounded-md border border-violet-200 bg-violet-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-violet-950">{execution.qualified_name}</p>
          <p className="mt-1 text-xs text-violet-800">
            Status: {execution.status} · Attempts: {execution.attempt_count} · Recoveries:{" "}
            {execution.recovery_count}
          </p>
        </div>
        <p className="font-mono text-xs text-violet-800">
          Key {execution.idempotency_key.slice(0, 12)}…
        </p>
      </div>
      <pre className="max-h-52 overflow-auto rounded bg-white/80 p-3 text-xs text-slate-700">
        <code>{JSON.stringify(execution.arguments, null, 2)}</code>
      </pre>
      {execution.error_message ? (
        <p className="text-xs text-violet-900">{execution.error_message}</p>
      ) : null}
      {unknown ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={reconciling || !onReconcile}
            onClick={() => onReconcile?.(execution, "confirm_succeeded")}
            className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          >
            Confirm succeeded
          </button>
          <button
            type="button"
            disabled={reconciling || !onReconcile}
            onClick={() => onReconcile?.(execution, "confirm_failed")}
            className="rounded-md border border-violet-300 bg-white px-3 py-2 text-sm font-medium text-violet-950 disabled:text-slate-400"
          >
            Confirm failed
          </button>
          {execution.retry_safe ? (
            <button
              type="button"
              disabled={reconciling || !onReconcile}
              onClick={() => onReconcile?.(execution, "retry")}
              className="rounded-md border border-violet-300 bg-white px-3 py-2 text-sm font-medium text-violet-950 disabled:text-slate-400"
            >
              Retry with same key
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ApprovalCard({
  approval,
  deciding,
  onDecision
}: {
  approval: MCPToolApproval;
  deciding: boolean;
  onDecision?: (
    approval: MCPToolApproval,
    decision: "approve" | "reject"
  ) => void;
}) {
  const pending = approval.status === "pending";
  return (
    <div className="space-y-3 rounded-md border border-amber-200 bg-amber-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-amber-950">{approval.qualified_name}</p>
          <p className="mt-1 text-xs text-amber-800">
            Policy: {approval.policy_snapshot} · Status: {approval.status}
          </p>
        </div>
        <p className="text-xs text-amber-800">
          Expires {new Date(approval.expires_at).toLocaleString()}
        </p>
      </div>
      <pre className="max-h-64 overflow-auto rounded bg-white/80 p-3 text-xs text-slate-700">
        <code>{JSON.stringify(approval.arguments, null, 2)}</code>
      </pre>
      {approval.decision_note ? (
        <p className="text-xs text-amber-900">Note: {approval.decision_note}</p>
      ) : null}
      {pending ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={deciding || !onDecision}
            onClick={() => onDecision?.(approval, "approve")}
            className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {deciding ? "Submitting..." : "Approve and resume"}
          </button>
          <button
            type="button"
            disabled={deciding || !onDecision}
            onClick={() => onDecision?.(approval, "reject")}
            className="rounded-md border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-950 hover:bg-amber-100 disabled:cursor-not-allowed disabled:text-slate-400"
          >
            Reject and resume
          </button>
        </div>
      ) : (
        <p className="text-xs font-medium text-amber-900">
          Decision: {approval.decision ?? approval.status}
          {approval.decided_by ? ` by ${approval.decided_by}` : ""}
        </p>
      )}
    </div>
  );
}

function readApproval(value: unknown): MCPToolApproval | null {
  if (typeof value !== "object" || value === null || !("approval" in value)) {
    return null;
  }
  const approval = (value as { approval?: unknown }).approval;
  if (
    typeof approval !== "object" ||
    approval === null ||
    !("id" in approval) ||
    !("qualified_name" in approval)
  ) {
    return null;
  }
  return approval as MCPToolApproval;
}

function readExecution(value: unknown): MCPToolExecution | null {
  if (typeof value !== "object" || value === null || !("execution" in value)) {
    return null;
  }
  const execution = (value as { execution?: unknown }).execution;
  if (
    typeof execution !== "object" ||
    execution === null ||
    !("id" in execution) ||
    !("qualified_name" in execution)
  ) {
    return null;
  }
  return execution as MCPToolExecution;
}

function readDiff(value: unknown) {
  if (typeof value === "object" && value !== null && "diff" in value) {
    const diff = (value as { diff?: unknown }).diff;
    return typeof diff === "string" ? diff : "";
  }
  return "";
}
