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
        暂无执行轨迹。
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {events.map((event, index) => (
        <article key={event.id} className="rounded-lg border border-border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase text-slate-500">步骤 {index + 1}</p>
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
  if (event.type === "agent_plan") {
    return `规划下一动作 · ${readPlannedAction(event.output) ?? "planner"}`;
  }
  if (event.type === "agent_observation") {
    return `Agent 观察结果 · ${event.tool_name ?? "本地动作"}`;
  }
  if (event.type === "agent_guardrail") {
    return `策略约束 · ${event.tool_name ?? "policy"}`;
  }
  if (event.type === "checkpoint_resume") {
    return "从检查点恢复";
  }
  if (event.type === "tool_call") {
    return `工具调用 · ${event.tool_name ?? "unknown"}`;
  }
  if (event.type === "tool_result") {
    return `工具结果 · ${event.tool_name ?? "unknown"}`;
  }
  if (event.type === "observation") {
    return `观察结果 · ${event.tool_name ?? "agent"}`;
  }
  if (event.type === "approval_required") {
    return `等待审批 · ${event.tool_name ?? "MCP 工具"}`;
  }
  if (event.type === "approval_decision") {
    return `审批决定 · ${event.tool_name ?? "MCP 工具"}`;
  }
  if (event.type === "mcp_execution") {
    return `MCP 执行 · ${event.tool_name ?? "MCP 工具"}`;
  }
  if (event.type === "patch") {
    return "补丁";
  }
  if (event.type === "inspection") {
    return "检查仓库";
  }
  if (event.type === "baseline_test_result") {
    return "复现失败";
  }
  if (event.type === "targeted_test_result") {
    return "目标测试";
  }
  if (event.type === "regression_test_result") {
    return "回归测试";
  }
  if (event.type === "test_result" || event.type === "verification") {
    return event.type === "verification" ? "验证结论" : "测试结果";
  }
  if (event.type === "reflection") {
    return "失败复盘";
  }
  if (event.type === "final") {
    return "最终结果";
  }
  if (event.type === "error") {
    return "错误";
  }
  return "计划";
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
  // Timeline payloads are sanitized observable actions/evidence, not hidden
  // model reasoning. Event type selects presentation but grants no authority.
  if (event.type === "approval_required") {
    const original = readApproval(event.output);
    if (original) {
      // Keep the immutable event while overlaying the latest mutable state
      // returned by approval/reconciliation APIs.
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
  if (
    event.type === "baseline_test_result" ||
    event.type === "targeted_test_result" ||
    event.type === "regression_test_result" ||
    event.type === "test_result" ||
    event.type === "verification"
  ) {
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
            状态： {execution.status} · 尝试次数： {execution.attempt_count} · 恢复次数：{" "}
            {execution.recovery_count}
          </p>
        </div>
        <p className="font-mono text-xs text-violet-800">
          幂等键 {execution.idempotency_key.slice(0, 12)}…
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
            确认成功
          </button>
          <button
            type="button"
            disabled={reconciling || !onReconcile}
            onClick={() => onReconcile?.(execution, "confirm_failed")}
            className="rounded-md border border-violet-300 bg-white px-3 py-2 text-sm font-medium text-violet-950 disabled:text-slate-400"
          >
            确认失败
          </button>
          {execution.retry_safe ? (
            <button
              type="button"
              disabled={reconciling || !onReconcile}
              onClick={() => onReconcile?.(execution, "retry")}
              className="rounded-md border border-violet-300 bg-white px-3 py-2 text-sm font-medium text-violet-950 disabled:text-slate-400"
            >
              使用相同幂等键重试
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
            策略： {approval.policy_snapshot} · 状态： {approval.status}
          </p>
        </div>
        <p className="text-xs text-amber-800">
          到期时间 {new Date(approval.expires_at).toLocaleString()}
        </p>
      </div>
      <pre className="max-h-64 overflow-auto rounded bg-white/80 p-3 text-xs text-slate-700">
        <code>{JSON.stringify(approval.arguments, null, 2)}</code>
      </pre>
      {approval.decision_note ? (
        <p className="text-xs text-amber-900">备注： {approval.decision_note}</p>
      ) : null}
      {pending ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={deciding || !onDecision}
            onClick={() => onDecision?.(approval, "approve")}
            className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {deciding ? "正在提交…" : "批准并继续"}
          </button>
          <button
            type="button"
            disabled={deciding || !onDecision}
            onClick={() => onDecision?.(approval, "reject")}
            className="rounded-md border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-950 hover:bg-amber-100 disabled:cursor-not-allowed disabled:text-slate-400"
          >
            拒绝并继续
          </button>
        </div>
      ) : (
        <p className="text-xs font-medium text-amber-900">
          审批决定： {approval.decision ?? approval.status}
          {approval.decided_by ? `，操作者：${approval.decided_by}` : ""}
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

function readPlannedAction(value: unknown) {
  if (typeof value !== "object" || value === null || !("action" in value)) {
    return null;
  }
  const planned = (value as { action?: unknown }).action;
  if (typeof planned !== "object" || planned === null || !("action" in planned)) {
    return null;
  }
  const actionName = (planned as { action?: unknown }).action;
  return typeof actionName === "string" ? actionName : null;
}
