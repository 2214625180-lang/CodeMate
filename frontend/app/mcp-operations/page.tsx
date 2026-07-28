"use client";

import { useCallback, useEffect, useState } from "react";

import {
  controlMCPCircuit,
  deliverSecurityAuditNow,
  getMCPComplianceReport,
  getMCPOperationsOverview,
  getSecurityAuditDeliveryStatus,
  probeMCPServers,
  requeueSecurityAuditDeadLetters,
  scanMCPCompliance
} from "@/lib/api";
import type {
  MCPComplianceReport,
  MCPOperationsOverview,
  MCPServerHealth,
  SecurityAuditDeliveryStatus
} from "@/lib/types";

export default function MCPOperationsPage() {
  const [overview, setOverview] = useState<MCPOperationsOverview | null>(null);
  const [auditDelivery, setAuditDelivery] = useState<SecurityAuditDeliveryStatus | null>(null);
  const [compliance, setCompliance] = useState<MCPComplianceReport | null>(null);
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [isLoading, setIsLoading] = useState(true);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [data, audit, complianceReport] = await Promise.all([
        getMCPOperationsOverview(windowMinutes),
        getSecurityAuditDeliveryStatus(),
        getMCPComplianceReport()
      ]);
      setOverview(data);
      setAuditDelivery(audit);
      setCompliance(complianceReport);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load MCP operations");
    } finally {
      setIsLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => {
    setIsLoading(true);
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function runProbe(serverName?: string) {
    const action = `probe:${serverName ?? "all"}`;
    setActiveAction(action);
    setError(null);
    try {
      const response = await probeMCPServers(serverName);
      setNotice(`Health probe queued: ${response.job_id}`);
      window.setTimeout(() => void load(), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to queue health probe");
    } finally {
      setActiveAction(null);
    }
  }

  async function updateCircuit(
    server: MCPServerHealth,
    action: "open" | "close" | "reset"
  ) {
    const actionId = `${action}:${server.server_name}`;
    setActiveAction(actionId);
    setError(null);
    try {
      await controlMCPCircuit(server.server_name, action, server.version);
      setNotice(`${server.server_name}: circuit ${action} completed`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update circuit");
    } finally {
      setActiveAction(null);
    }
  }

  async function drainAuditOutbox() {
    setActiveAction("audit-deliver");
    setError(null);
    try {
      const result = await deliverSecurityAuditNow();
      setNotice(`Audit delivery: ${result.delivered ?? 0} delivered, ${result.retry ?? 0} retry`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to deliver security audit events");
    } finally {
      setActiveAction(null);
    }
  }

  async function requeueAuditDeadLetters() {
    setActiveAction("audit-requeue");
    setError(null);
    try {
      const result = await requeueSecurityAuditDeadLetters();
      setNotice(`Audit delivery: ${result.requeued} dead letters requeued`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to requeue audit dead letters");
    } finally {
      setActiveAction(null);
    }
  }

  async function runComplianceScan() {
    setActiveAction("compliance-scan");
    setError(null);
    try {
      const result = await scanMCPCompliance();
      setNotice(`Compliance scan queued: ${result.job_id}`);
      window.setTimeout(() => void load(), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to queue compliance scan");
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">MCP Control Plane</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">Operations Dashboard</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Server health, execution latency, circuit breakers, recovery backlog and alerts.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={windowMinutes}
            onChange={(event) => setWindowMinutes(Number(event.target.value))}
            className="rounded-md border border-border bg-white px-3 py-2 text-sm"
          >
            <option value={15}>Last 15 minutes</option>
            <option value={60}>Last hour</option>
            <option value={360}>Last 6 hours</option>
            <option value={1440}>Last 24 hours</option>
          </select>
          <button
            type="button"
            disabled={activeAction !== null}
            onClick={() => void runProbe()}
            className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          >
            Probe all servers
          </button>
          <a
            href="/api/backend/mcp-operations/metrics/prometheus"
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-border bg-white px-3 py-2 text-sm font-medium text-slate-700"
          >
            Prometheus
          </a>
        </div>
      </header>

      {error ? <Notice tone="error">{error}</Notice> : null}
      {notice ? <Notice tone="info">{notice}</Notice> : null}

      {isLoading && !overview ? (
        <div className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          Loading MCP operations...
        </div>
      ) : overview ? (
        <>
          <Summary overview={overview} />
          {compliance ? (
            <Compliance
              report={compliance}
              disabled={activeAction !== null}
              onScan={runComplianceScan}
            />
          ) : null}
          {auditDelivery ? (
            <AuditDelivery
              status={auditDelivery}
              disabled={activeAction !== null}
              onDeliver={drainAuditOutbox}
              onRequeue={requeueAuditDeadLetters}
            />
          ) : null}
          <Alerts overview={overview} />
          <ServerHealthTable
            servers={overview.servers}
            activeAction={activeAction}
            onProbe={runProbe}
            onCircuit={updateCircuit}
          />
          <ServerMetrics overview={overview} />
          <RecentExecutions overview={overview} />
          <p className="text-xs text-slate-500">
            Updated {new Date(overview.generated_at).toLocaleString()} · automatic refresh every
            10 seconds
          </p>
        </>
      ) : null}
    </div>
  );
}

function Compliance({
  report,
  disabled,
  onScan
}: {
  report: MCPComplianceReport;
  disabled: boolean;
  onScan: () => Promise<void>;
}) {
  const failed = report.controls.filter((item) => item.status === "failed");
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Sandbox & egress compliance</h2>
          <p className="mt-1 text-sm text-slate-500">
            Status: {report.status} · {report.controls.length} controls · {failed.length} failed
          </p>
        </div>
        <button type="button" disabled={disabled} onClick={() => void onScan()} className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:text-slate-400">Scan now</button>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-2">
        {report.controls.map((item) => (
          <div key={item.id} className={`rounded-md border p-3 text-sm ${item.status === "passed" ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
            <span className="font-mono text-xs">{item.id}</span>
            <p className="mt-1 font-medium">{item.title}</p>
          </div>
        ))}
        {!report.controls.length ? <p className="text-sm text-amber-700">No valid compliance report yet.</p> : null}
      </div>
    </section>
  );
}

function AuditDelivery({
  status,
  disabled,
  onDeliver,
  onRequeue
}: {
  status: SecurityAuditDeliveryStatus;
  disabled: boolean;
  onDeliver: () => Promise<void>;
  onRequeue: () => Promise<void>;
}) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Security audit delivery</h2>
          <p className="mt-1 text-sm text-slate-500">
            Sinks: {status.configured_sinks.join(", ") || "disabled"} · oldest undelivered {status.oldest_undelivered_seconds.toFixed(0)}s
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" disabled={disabled} onClick={() => void onRequeue()} className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:text-slate-400">Requeue dead letters</button>
          <button type="button" disabled={disabled} onClick={() => void onDeliver()} className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:text-slate-400">Deliver now</button>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        {Object.entries(status.counts).map(([name, count]) => (
          <span key={name} className="rounded bg-slate-100 px-3 py-1 text-slate-700">{name}: {count}</span>
        ))}
        {!Object.keys(status.counts).length ? <span className="text-emerald-700">Outbox empty</span> : null}
      </div>
    </section>
  );
}

function Summary({ overview }: { overview: MCPOperationsOverview }) {
  const cards = [
    ["Executions", overview.summary.executions],
    ["Succeeded", overview.summary.succeeded],
    ["Failed", overview.summary.failed],
    ["Unknown", overview.summary.unknown],
    ["Open circuits", overview.summary.open_circuits],
    ["Unhealthy", overview.summary.unhealthy_servers],
    ["Deduplicated", overview.summary.deduplication_hits],
    ["P95 latency", `${overview.latency_ms.p95.toFixed(0)} ms`],
    ["Requests/min", overview.summary.requests_per_minute.toFixed(2)]
  ];
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(([label, value]) => (
        <article key={label} className="rounded-lg border border-border bg-white p-4">
          <p className="text-xs font-medium uppercase text-slate-500">{label}</p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p>
        </article>
      ))}
    </section>
  );
}

function Alerts({ overview }: { overview: MCPOperationsOverview }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-950">Active alerts</h2>
        <span className="text-sm text-slate-500">{overview.alerts.length}</span>
      </div>
      {overview.alerts.length ? (
        <div className="mt-4 space-y-2">
          {overview.alerts.map((alert, index) => (
            <div
              key={`${alert.type}-${alert.server_name}-${alert.execution_id ?? index}`}
              className={`rounded-md border p-3 text-sm ${
                alert.severity === "critical"
                  ? "border-red-200 bg-red-50 text-red-900"
                  : "border-amber-200 bg-amber-50 text-amber-900"
              }`}
            >
              <span className="font-semibold">{alert.server_name}</span> · {alert.message}
              {alert.execution_id ? (
                <span className="ml-2 font-mono text-xs">{alert.execution_id}</span>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm text-emerald-700">No active MCP alerts.</p>
      )}
    </section>
  );
}

function ServerHealthTable({
  servers,
  activeAction,
  onProbe,
  onCircuit
}: {
  servers: MCPServerHealth[];
  activeAction: string | null;
  onProbe: (serverName?: string) => Promise<void>;
  onCircuit: (
    server: MCPServerHealth,
    action: "open" | "close" | "reset"
  ) => Promise<void>;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-white">
      <div className="border-b border-border p-5">
        <h2 className="text-lg font-semibold text-slate-950">Server health and circuits</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Server</th>
              <th className="px-4 py-3">Health</th>
              <th className="px-4 py-3">Circuit</th>
              <th className="px-4 py-3">Latency</th>
              <th className="px-4 py-3">Failures</th>
              <th className="px-4 py-3">Last probe</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {servers.map((server) => (
              <tr key={server.server_name}>
                <td className="px-4 py-3">
                  <p className="font-medium text-slate-950">{server.server_name}</p>
                  <p className="max-w-52 truncate text-xs text-slate-500">{server.public_url}</p>
                </td>
                <td className="px-4 py-3"><Status value={server.operational_status} /></td>
                <td className="px-4 py-3"><Status value={server.circuit_state} /></td>
                <td className="px-4 py-3">{formatLatency(server.last_latency_ms)}</td>
                <td className="px-4 py-3">{server.consecutive_failures}</td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {server.last_probe_at ? new Date(server.last_probe_at).toLocaleString() : "Never"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    <ActionButton
                      label="Probe"
                      disabled={activeAction !== null}
                      onClick={() => void onProbe(server.server_name)}
                    />
                    <ActionButton
                      label={server.circuit_state === "open" ? "Close" : "Open"}
                      disabled={activeAction !== null}
                      onClick={() =>
                        void onCircuit(
                          server,
                          server.circuit_state === "open" ? "close" : "open"
                        )
                      }
                    />
                    <ActionButton
                      label="Reset"
                      disabled={activeAction !== null}
                      onClick={() => void onCircuit(server, "reset")}
                    />
                  </div>
                </td>
              </tr>
            ))}
            {!servers.length ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-500">No MCP servers configured.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ServerMetrics({ overview }: { overview: MCPOperationsOverview }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">Metrics by server</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {overview.per_server.map((server) => (
          <article key={server.server_name} className="rounded-md border border-border p-4">
            <div className="flex items-center justify-between">
              <p className="font-semibold text-slate-950">{server.server_name}</p>
              <span className="text-xs text-slate-500">{server.calls} calls</span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-600">
              <p>Success: {server.succeeded}</p><p>Failed: {server.failed}</p>
              <p>Unknown: {server.unknown}</p><p>Error: {(server.error_rate * 100).toFixed(1)}%</p>
              <p>P50: {formatLatency(server.latency_ms.p50)}</p>
              <p>P95: {formatLatency(server.latency_ms.p95)}</p>
            </div>
          </article>
        ))}
      </div>
      {overview.per_tool.length ? (
        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full divide-y divide-border text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="py-2">Tool</th><th className="py-2">Calls</th><th className="py-2">Success</th><th className="py-2">Failed</th><th className="py-2">Unknown</th><th className="py-2">P95</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {overview.per_tool.map((tool) => (
                <tr key={tool.qualified_name}>
                  <td className="py-2 font-medium text-slate-950">{tool.qualified_name}</td>
                  <td className="py-2">{tool.calls}</td><td className="py-2">{tool.succeeded}</td>
                  <td className="py-2">{tool.failed}</td><td className="py-2">{tool.unknown}</td>
                  <td className="py-2">{formatLatency(tool.latency_ms.p95)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function RecentExecutions({ overview }: { overview: MCPOperationsOverview }) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-white">
      <div className="border-b border-border p-5">
        <h2 className="text-lg font-semibold text-slate-950">Recent executions</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-4 py-3">Tool</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Latency</th><th className="px-4 py-3">Attempts</th><th className="px-4 py-3">Time</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {overview.recent_executions.map((execution) => (
              <tr key={execution.id}>
                <td className="px-4 py-3"><p className="font-medium text-slate-950">{execution.qualified_name}</p><p className="font-mono text-xs text-slate-500">{execution.id}</p></td>
                <td className="px-4 py-3"><Status value={execution.status} /></td>
                <td className="px-4 py-3">{formatLatency(execution.latency_ms)}</td>
                <td className="px-4 py-3">{execution.attempt_count} / recovery {execution.recovery_count}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{new Date(execution.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Status({ value }: { value: string }) {
  const good = value === "healthy" || value === "closed" || value === "succeeded";
  const bad = value === "unhealthy" || value === "open" || value === "failed" || value === "unknown";
  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${good ? "bg-emerald-50 text-emerald-700" : bad ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{value}</span>;
}

function ActionButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return <button type="button" disabled={disabled} onClick={onClick} className="rounded border border-border px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-400">{label}</button>;
}

function Notice({ children, tone }: { children: React.ReactNode; tone: "error" | "info" }) {
  return <div className={`rounded-md p-3 text-sm ${tone === "error" ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-700"}`}>{children}</div>;
}

function formatLatency(value: number | null) {
  return value === null ? "—" : `${value.toFixed(0)} ms`;
}
