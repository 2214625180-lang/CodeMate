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
      setError(err instanceof Error ? err.message : "加载 MCP 运维数据失败");
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
      setNotice(`健康探测已入队：${response.job_id}`);
      window.setTimeout(() => void load(), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "健康探测入队失败");
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
      setNotice(`${server.server_name}：熔断器操作 ${action} 已完成`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新熔断器失败");
    } finally {
      setActiveAction(null);
    }
  }

  async function drainAuditOutbox() {
    setActiveAction("audit-deliver");
    setError(null);
    try {
      const result = await deliverSecurityAuditNow();
      setNotice(`审计投递：${result.delivered ?? 0} 条已投递，${result.retry ?? 0} 条待重试`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "投递安全审计事件失败");
    } finally {
      setActiveAction(null);
    }
  }

  async function requeueAuditDeadLetters() {
    setActiveAction("audit-requeue");
    setError(null);
    try {
      const result = await requeueSecurityAuditDeadLetters();
      setNotice(`审计投递：${result.requeued} 条死信已重新入队`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "审计死信重新入队失败");
    } finally {
      setActiveAction(null);
    }
  }

  async function runComplianceScan() {
    setActiveAction("compliance-scan");
    setError(null);
    try {
      const result = await scanMCPCompliance();
      setNotice(`合规扫描已入队：${result.job_id}`);
      window.setTimeout(() => void load(), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "合规扫描入队失败");
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">MCP 控制平面</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">运维面板</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            查看服务健康、执行耗时、熔断器、待恢复任务和告警。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={windowMinutes}
            onChange={(event) => setWindowMinutes(Number(event.target.value))}
            className="rounded-md border border-border bg-white px-3 py-2 text-sm"
          >
            <option value={15}>最近 15 分钟</option>
            <option value={60}>最近 1 小时</option>
            <option value={360}>最近 6 小时</option>
            <option value={1440}>最近 24 小时</option>
          </select>
          <button
            type="button"
            disabled={activeAction !== null}
            onClick={() => void runProbe()}
            className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          >
            探测全部服务
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
          正在加载 MCP 运维数据…
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
            更新时间 {new Date(overview.generated_at).toLocaleString()} · 每 10 秒自动刷新
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
          <h2 className="text-lg font-semibold text-slate-950">沙箱与出站访问合规</h2>
          <p className="mt-1 text-sm text-slate-500">
            状态： {report.status} · {report.controls.length} 项检查 · {failed.length} failed
          </p>
        </div>
        <button type="button" disabled={disabled} onClick={() => void onScan()} className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:text-slate-400">立即扫描</button>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-2">
        {report.controls.map((item) => (
          <div key={item.id} className={`rounded-md border p-3 text-sm ${item.status === "passed" ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
            <span className="font-mono text-xs">{item.id}</span>
            <p className="mt-1 font-medium">{item.title}</p>
          </div>
        ))}
        {!report.controls.length ? <p className="text-sm text-amber-700">暂无有效的合规报告。</p> : null}
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
          <h2 className="text-lg font-semibold text-slate-950">安全审计投递</h2>
          <p className="mt-1 text-sm text-slate-500">
            接收端： {status.configured_sinks.join(", ") || "disabled"} · 最早未投递时间 {status.oldest_undelivered_seconds.toFixed(0)}s
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" disabled={disabled} onClick={() => void onRequeue()} className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:text-slate-400">死信重新入队</button>
          <button type="button" disabled={disabled} onClick={() => void onDeliver()} className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:text-slate-400">立即投递</button>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        {Object.entries(status.counts).map(([name, count]) => (
          <span key={name} className="rounded bg-slate-100 px-3 py-1 text-slate-700">{name}: {count}</span>
        ))}
        {!Object.keys(status.counts).length ? <span className="text-emerald-700">无待投递事件</span> : null}
      </div>
    </section>
  );
}

function Summary({ overview }: { overview: MCPOperationsOverview }) {
  const cards = [
    ["执行次数", overview.summary.executions],
    ["成功", overview.summary.succeeded],
    ["失败", overview.summary.failed],
    ["未知", overview.summary.unknown],
    ["已熔断", overview.summary.open_circuits],
    ["不健康", overview.summary.unhealthy_servers],
    ["已去重", overview.summary.deduplication_hits],
    ["P95 耗时", `${overview.latency_ms.p95.toFixed(0)} ms`],
    ["每分钟请求数", overview.summary.requests_per_minute.toFixed(2)]
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
        <h2 className="text-lg font-semibold text-slate-950">当前告警</h2>
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
        <p className="mt-4 text-sm text-emerald-700">当前无 MCP 告警。</p>
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
        <h2 className="text-lg font-semibold text-slate-950">服务健康与熔断状态</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">服务</th>
              <th className="px-4 py-3">健康状态</th>
              <th className="px-4 py-3">熔断状态</th>
              <th className="px-4 py-3">耗时</th>
              <th className="px-4 py-3">失败次数</th>
              <th className="px-4 py-3">上次探测</th>
              <th className="px-4 py-3">操作</th>
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
                  {server.last_probe_at ? new Date(server.last_probe_at).toLocaleString() : "从未"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    <ActionButton
                      label="探测"
                      disabled={activeAction !== null}
                      onClick={() => void onProbe(server.server_name)}
                    />
                    <ActionButton
                      label={server.circuit_state === "open" ? "关闭熔断" : "开启熔断"}
                      disabled={activeAction !== null}
                      onClick={() =>
                        void onCircuit(
                          server,
                          server.circuit_state === "open" ? "close" : "open"
                        )
                      }
                    />
                    <ActionButton
                      label="重置"
                      disabled={activeAction !== null}
                      onClick={() => void onCircuit(server, "reset")}
                    />
                  </div>
                </td>
              </tr>
            ))}
            {!servers.length ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-500">尚未配置 MCP 服务。</td></tr>
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
      <h2 className="text-lg font-semibold text-slate-950">按服务统计指标</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {overview.per_server.map((server) => (
          <article key={server.server_name} className="rounded-md border border-border p-4">
            <div className="flex items-center justify-between">
              <p className="font-semibold text-slate-950">{server.server_name}</p>
              <span className="text-xs text-slate-500">{server.calls} calls</span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-600">
              <p>成功： {server.succeeded}</p><p>失败： {server.failed}</p>
              <p>未知： {server.unknown}</p><p>错误： {(server.error_rate * 100).toFixed(1)}%</p>
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
              <tr><th className="py-2">工具</th><th className="py-2">调用次数</th><th className="py-2">成功</th><th className="py-2">失败</th><th className="py-2">未知</th><th className="py-2">P95</th></tr>
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
        <h2 className="text-lg font-semibold text-slate-950">最近执行</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-4 py-3">工具</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">耗时</th><th className="px-4 py-3">尝试次数</th><th className="px-4 py-3">时间</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {overview.recent_executions.map((execution) => (
              <tr key={execution.id}>
                <td className="px-4 py-3"><p className="font-medium text-slate-950">{execution.qualified_name}</p><p className="font-mono text-xs text-slate-500">{execution.id}</p></td>
                <td className="px-4 py-3"><Status value={execution.status} /></td>
                <td className="px-4 py-3">{formatLatency(execution.latency_ms)}</td>
                <td className="px-4 py-3">{execution.attempt_count} / 恢复次数 {execution.recovery_count}</td>
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
