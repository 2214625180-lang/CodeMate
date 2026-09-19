"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createMCPQuotaPolicy,
  applyMCPQuotaRetention,
  disableMCPQuotaPolicy,
  getMCPQuotaOverview,
  listMCPTenants,
  resetMCPQuotaPolicy,
  reconcileMCPQuotaUsage,
  temporarilyAdjustMCPQuotaPolicy,
  updateMCPQuotaPolicy
} from "@/lib/api";
import type { MCPQuotaOverview, MCPQuotaPolicy, MCPTenant } from "@/lib/types";

export default function MCPQuotasPage() {
  const [tenants, setTenants] = useState<MCPTenant[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [overview, setOverview] = useState<MCPQuotaOverview | null>(null);
  const [windowDays, setWindowDays] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const nextTenants = await listMCPTenants();
    setTenants(nextTenants);
    const selected = tenantId ?? nextTenants[0]?.id ?? null;
    setTenantId(selected);
    if (selected) setOverview(await getMCPQuotaOverview(selected, windowDays));
  }, [tenantId, windowDays]);

  useEffect(() => {
    void load().catch(showError);
    const timer = window.setInterval(() => void load().catch(showError), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  function showError(err: unknown) {
    setError(err instanceof Error ? err.message : "MCP 配额操作失败");
  }

  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setNotice(message);
      await load();
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  }

  async function createPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenantId) return;
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    await perform(
      () => createMCPQuotaPolicy(tenantId, {
        repo_id: stringValue(data.repo_id) || null,
        principal_type: stringValue(data.principal_type) || "*",
        principal_id: stringValue(data.principal_id) || "*",
        server_name: stringValue(data.server_name) || "*",
        tool_name: stringValue(data.tool_name) || "*",
        rate_limit_per_minute: numberValue(data.rate_limit_per_minute),
        daily_call_limit: numberValue(data.daily_call_limit),
        daily_cost_limit: numberValue(data.daily_cost_limit),
        concurrent_limit: numberValue(data.concurrent_limit),
        run_call_limit: numberValue(data.run_call_limit),
        max_run_duration_seconds: numberValue(data.max_run_duration_seconds),
        call_cost_units: numberValue(data.call_cost_units) ?? 1,
        warning_threshold: (numberValue(data.warning_percent) ?? 80) / 100
      }),
      "配额策略已创建。"
    );
    event.currentTarget.reset();
  }

  async function adjustPolicy(policy: MCPQuotaPolicy) {
    const value = window.prompt(
      "新的每日调用上限（更新时会检查策略版本）：",
      String(policy.daily_call_limit ?? "")
    );
    if (!value) return;
    const minutes = window.prompt("临时调整持续时间（分钟）：", "60");
    if (!minutes) return;
    await perform(
      () => temporarilyAdjustMCPQuotaPolicy(
        policy,
        { daily_call_limit: Number(value) },
        Number(minutes) * 60
      ),
      "已应用每日预算的临时调整。"
    );
  }

  async function reconcile(repair: boolean) {
    if (!tenantId) return;
    await perform(async () => {
      const report = await reconcileMCPQuotaUsage(tenantId, repair);
      setNotice(`对账结果：${String(report.status ?? "completed")}`);
    }, repair ? "配额计数已完成对账。" : "配额偏差审计已完成。");
  }

  async function retention(dryRun: boolean) {
    if (!tenantId) return;
    await perform(async () => {
      const report = await applyMCPQuotaRetention(tenantId, 90, dryRun);
      setNotice(`${dryRun ? "保留策略预览" : "已应用保留策略"}: ${report.events} 条事件，${report.rejections} 条拒绝记录。`);
    }, dryRun ? "保留策略预览已完成。" : "旧配额记录已清理。");
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">MCP 控制平面</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">配额与预算管理</h1>
          <p className="mt-2 text-sm text-slate-600">
            按租户、仓库、主体、服务和工具设置限额，并以幂等方式计费。
          </p>
        </div>
        <div className="flex gap-2">
          <select value={tenantId ?? ""} onChange={(event) => setTenantId(event.target.value || null)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">
            {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
          </select>
          <select value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))} className="rounded-md border border-border bg-white px-3 py-2 text-sm">
            <option value={1}>24 小时</option><option value={7}>7 天</option><option value={30}>30 天</option>
          </select>
          {tenantId ? <a href={`/api/backend/mcp-quotas/tenants/${tenantId}/metrics/prometheus`} target="_blank" rel="noreferrer" className="rounded-md border border-border bg-white px-3 py-2 text-sm">Prometheus</a> : null}
          <button type="button" disabled={busy || !tenantId} onClick={() => void reconcile(false)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">检查计数偏差</button>
          <button type="button" disabled={busy || !tenantId} onClick={() => void reconcile(true)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">修复计数偏差</button>
          <button type="button" disabled={busy || !tenantId} onClick={() => void retention(true)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">保留策略预览</button>
        </div>
      </header>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {notice ? <Notice tone="info">{notice}</Notice> : null}
      {overview ? <Summary overview={overview} /> : null}
      {overview?.alerts.length ? <section className="space-y-2">{overview.alerts.map((alert, index) => <Notice key={`${alert.type}-${index}`} tone={alert.severity === "critical" ? "error" : "warning"}>{alert.message}</Notice>)}</section> : null}

      <form onSubmit={(event) => void createPolicy(event)} className="rounded-lg border border-border bg-white p-5">
        <h2 className="font-semibold text-slate-950">创建指定范围的配额策略</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Input name="repo_id" placeholder="仓库 UUID（可选）" />
          <Input name="principal_type" placeholder="主体类型：* / user / role / service / agent" defaultValue="*" />
          <Input name="principal_id" placeholder="主体 ID" defaultValue="*" />
          <Input name="server_name" placeholder="server" defaultValue="*" />
          <Input name="tool_name" placeholder="tool" defaultValue="*" />
          <Input name="rate_limit_per_minute" placeholder="calls/minute" type="number" />
          <Input name="daily_call_limit" placeholder="每日调用次数" type="number" />
          <Input name="daily_cost_limit" placeholder="每日费用单位" type="number" />
          <Input name="concurrent_limit" placeholder="concurrency" type="number" />
          <Input name="run_call_limit" placeholder="每次 Agent 运行的调用次数" type="number" />
          <Input name="max_run_duration_seconds" placeholder="单次运行最长时间（秒）" type="number" />
          <Input name="call_cost_units" placeholder="每次调用费用" type="number" defaultValue="1" />
          <Input name="warning_percent" placeholder="预警阈值（%）" type="number" defaultValue="80" />
        </div>
        <button type="submit" disabled={busy || !tenantId} className="mt-4 rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">创建策略</button>
      </form>

      {overview ? (
        <>
          <section className="overflow-hidden rounded-lg border border-border bg-white">
            <div className="border-b border-border p-5"><h2 className="font-semibold">策略与实时用量</h2></div>
            <div className="overflow-x-auto"><table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">适用范围</th><th className="px-4 py-3">限额</th><th className="px-4 py-3">用量</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">操作</th></tr></thead>
              <tbody className="divide-y divide-border">{overview.policies.map((policy) => <tr key={policy.id}>
                <td className="px-4 py-3"><p className="font-medium">{policy.server_name}.{policy.tool_name}</p><p className="text-xs text-slate-500">{policy.principal_type}:{policy.principal_id}{policy.repo_id ? ` · 仓库 ${policy.repo_id}` : ""}</p></td>
                <td className="px-4 py-3 text-xs"><p>{policy.effective_limits.rate_limit_per_minute ?? "∞"}/分钟 · {policy.effective_limits.daily_call_limit ?? "∞"}/天</p><p>{policy.effective_limits.concurrent_limit ?? "∞"} 个并发 · {policy.effective_limits.daily_cost_limit ?? "∞"} 费用单位/天</p>{policy.temporary_override_expires_at && new Date(policy.temporary_override_expires_at) > new Date() ? <p className="text-amber-700">临时调整截止时间 {new Date(policy.temporary_override_expires_at).toLocaleString()}</p> : null}</td>
                <td className="px-4 py-3"><p>{(policy.utilization * 100).toFixed(0)}%</p><p className="text-xs text-slate-500">{policy.usage.daily_calls} 次调用 · {policy.usage.daily_cost.toFixed(1)} 费用单位</p></td>
                <td className="px-4 py-3"><Status policy={policy} /></td>
                <td className="px-4 py-3"><div className="flex flex-wrap gap-1"><Action label="调整" disabled={busy || !policy.enabled} onClick={() => void adjustPolicy(policy)} /><Action label={policy.frozen ? "解冻" : "冻结"} disabled={busy || !policy.enabled} onClick={() => void perform(() => updateMCPQuotaPolicy(policy, { frozen: !policy.frozen }), policy.frozen ? "策略已解冻。" : "策略已冻结。")} /><Action label="重置" disabled={busy || !policy.enabled} onClick={() => void perform(() => resetMCPQuotaPolicy(policy), "用量窗口已重置。")} /><Action label="禁用" disabled={busy || !policy.enabled} onClick={() => void perform(() => disableMCPQuotaPolicy(policy.id), "策略已禁用。")} /></div></td>
              </tr>)}</tbody>
            </table></div>
          </section>
          <Breakdowns overview={overview} />
          <RecentRejections overview={overview} />
          <p className="text-xs text-slate-500">更新时间 {new Date(overview.generated_at).toLocaleString()} · 每 10 秒刷新</p>
        </>
      ) : null}
    </div>
  );
}

function Summary({ overview }: { overview: MCPQuotaOverview }) {
  const cards = [["调用次数", overview.summary.calls], ["费用单位", overview.summary.cost_units.toFixed(1)], ["已拒绝", overview.summary.rejections], ["并发数", overview.summary.active_concurrency], ["委托调用", overview.summary.delegated_user_calls]];
  return <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{cards.map(([label, value]) => <article key={label} className="rounded-lg border border-border bg-white p-4"><p className="text-xs uppercase text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></article>)}</section>;
}

function Breakdowns({ overview }: { overview: MCPQuotaOverview }) {
  return <section className="grid gap-4 md:grid-cols-3"><Rank title="按服务" items={overview.per_server} /><Rank title="按工具" items={overview.per_tool} /><Rank title="按主体" items={overview.per_principal} /></section>;
}

function Rank({ title, items }: { title: string; items: Array<[string, number]> }) {
  return <article className="rounded-lg border border-border bg-white p-5"><h2 className="font-semibold">{title}</h2><div className="mt-3 space-y-2">{items.slice(0, 10).map(([name, count]) => <div key={name} className="flex justify-between gap-3 text-sm"><span className="truncate">{name}</span><span>{count}</span></div>)}</div></article>;
}

function RecentRejections({ overview }: { overview: MCPQuotaOverview }) {
  return <section className="rounded-lg border border-border bg-white p-5"><h2 className="font-semibold">最近拒绝记录</h2><div className="mt-3 space-y-2">{overview.recent_rejections.map((item) => <div key={item.id} className="rounded border border-border p-3 text-sm"><span className="font-medium">{item.server_name}.{item.tool_name}</span> · {item.reason}<span className="ml-2 text-xs text-slate-500">{item.principal} · {new Date(item.created_at).toLocaleString()}</span></div>)}{!overview.recent_rejections.length ? <p className="text-sm text-emerald-700">暂无配额拒绝记录。</p> : null}</div></section>;
}

function Input({ name, placeholder, type = "text", defaultValue }: { name: string; placeholder: string; type?: string; defaultValue?: string }) {
  return <input name={name} type={type} min={type === "number" ? "0.01" : undefined} step={type === "number" ? "any" : undefined} defaultValue={defaultValue} placeholder={placeholder} aria-label={name} className="rounded-md border border-border px-3 py-2 text-sm" />;
}

function Status({ policy }: { policy: MCPQuotaPolicy }) {
  const value = !policy.enabled ? "disabled" : policy.frozen ? "frozen" : "active";
  return <span className={`rounded-full px-2 py-1 text-xs ${value === "active" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{value}</span>;
}

function Action({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return <button type="button" disabled={disabled} onClick={onClick} className="rounded border border-border px-2 py-1 text-xs disabled:text-slate-400">{label}</button>;
}

function Notice({ tone, children }: { tone: "error" | "warning" | "info"; children: React.ReactNode }) {
  const style = tone === "error" ? "bg-red-50 text-red-800" : tone === "warning" ? "bg-amber-50 text-amber-900" : "bg-blue-50 text-blue-800";
  return <div className={`rounded-md p-3 text-sm ${style}`}>{children}</div>;
}

function stringValue(value: FormDataEntryValue | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function numberValue(value: FormDataEntryValue | undefined): number | null {
  const text = stringValue(value);
  return text ? Number(text) : null;
}
