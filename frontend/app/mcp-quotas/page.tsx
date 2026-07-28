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
    setError(err instanceof Error ? err.message : "MCP quota operation failed");
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
      "Quota policy created."
    );
    event.currentTarget.reset();
  }

  async function adjustPolicy(policy: MCPQuotaPolicy) {
    const value = window.prompt(
      "New daily call limit (the policy update is version checked):",
      String(policy.daily_call_limit ?? "")
    );
    if (!value) return;
    const minutes = window.prompt("Temporary adjustment duration in minutes:", "60");
    if (!minutes) return;
    await perform(
      () => temporarilyAdjustMCPQuotaPolicy(
        policy,
        { daily_call_limit: Number(value) },
        Number(minutes) * 60
      ),
      "Temporary daily budget adjustment applied."
    );
  }

  async function reconcile(repair: boolean) {
    if (!tenantId) return;
    await perform(async () => {
      const report = await reconcileMCPQuotaUsage(tenantId, repair);
      setNotice(`Reconciliation: ${String(report.status ?? "completed")}`);
    }, repair ? "Quota counters reconciled." : "Quota drift audit completed.");
  }

  async function retention(dryRun: boolean) {
    if (!tenantId) return;
    await perform(async () => {
      const report = await applyMCPQuotaRetention(tenantId, 90, dryRun);
      setNotice(`${dryRun ? "Retention preview" : "Retention applied"}: ${report.events} events, ${report.rejections} rejections.`);
    }, dryRun ? "Retention preview completed." : "Old quota evidence purged.");
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">MCP Control Plane</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">Quota & Budget Governance</h1>
          <p className="mt-2 text-sm text-slate-600">
            Tenant, repository, principal, server and tool limits with idempotent charging.
          </p>
        </div>
        <div className="flex gap-2">
          <select value={tenantId ?? ""} onChange={(event) => setTenantId(event.target.value || null)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">
            {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
          </select>
          <select value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))} className="rounded-md border border-border bg-white px-3 py-2 text-sm">
            <option value={1}>24 hours</option><option value={7}>7 days</option><option value={30}>30 days</option>
          </select>
          {tenantId ? <a href={`/api/backend/mcp-quotas/tenants/${tenantId}/metrics/prometheus`} target="_blank" rel="noreferrer" className="rounded-md border border-border bg-white px-3 py-2 text-sm">Prometheus</a> : null}
          <button type="button" disabled={busy || !tenantId} onClick={() => void reconcile(false)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">Audit drift</button>
          <button type="button" disabled={busy || !tenantId} onClick={() => void reconcile(true)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">Repair drift</button>
          <button type="button" disabled={busy || !tenantId} onClick={() => void retention(true)} className="rounded-md border border-border bg-white px-3 py-2 text-sm">Retention preview</button>
        </div>
      </header>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {notice ? <Notice tone="info">{notice}</Notice> : null}
      {overview ? <Summary overview={overview} /> : null}
      {overview?.alerts.length ? <section className="space-y-2">{overview.alerts.map((alert, index) => <Notice key={`${alert.type}-${index}`} tone={alert.severity === "critical" ? "error" : "warning"}>{alert.message}</Notice>)}</section> : null}

      <form onSubmit={(event) => void createPolicy(event)} className="rounded-lg border border-border bg-white p-5">
        <h2 className="font-semibold text-slate-950">Create scoped quota policy</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Input name="repo_id" placeholder="Repository UUID (optional)" />
          <Input name="principal_type" placeholder="principal type: * / user / role / service / agent" defaultValue="*" />
          <Input name="principal_id" placeholder="principal ID" defaultValue="*" />
          <Input name="server_name" placeholder="server" defaultValue="*" />
          <Input name="tool_name" placeholder="tool" defaultValue="*" />
          <Input name="rate_limit_per_minute" placeholder="calls/minute" type="number" />
          <Input name="daily_call_limit" placeholder="daily calls" type="number" />
          <Input name="daily_cost_limit" placeholder="daily cost units" type="number" />
          <Input name="concurrent_limit" placeholder="concurrency" type="number" />
          <Input name="run_call_limit" placeholder="calls per Agent Run" type="number" />
          <Input name="max_run_duration_seconds" placeholder="max Run duration seconds" type="number" />
          <Input name="call_cost_units" placeholder="cost per call" type="number" defaultValue="1" />
          <Input name="warning_percent" placeholder="warning %" type="number" defaultValue="80" />
        </div>
        <button type="submit" disabled={busy || !tenantId} className="mt-4 rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">Create policy</button>
      </form>

      {overview ? (
        <>
          <section className="overflow-hidden rounded-lg border border-border bg-white">
            <div className="border-b border-border p-5"><h2 className="font-semibold">Policies and live usage</h2></div>
            <div className="overflow-x-auto"><table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">Scope</th><th className="px-4 py-3">Limits</th><th className="px-4 py-3">Usage</th><th className="px-4 py-3">State</th><th className="px-4 py-3">Actions</th></tr></thead>
              <tbody className="divide-y divide-border">{overview.policies.map((policy) => <tr key={policy.id}>
                <td className="px-4 py-3"><p className="font-medium">{policy.server_name}.{policy.tool_name}</p><p className="text-xs text-slate-500">{policy.principal_type}:{policy.principal_id}{policy.repo_id ? ` · repo ${policy.repo_id}` : ""}</p></td>
                <td className="px-4 py-3 text-xs"><p>{policy.effective_limits.rate_limit_per_minute ?? "∞"}/min · {policy.effective_limits.daily_call_limit ?? "∞"}/day</p><p>{policy.effective_limits.concurrent_limit ?? "∞"} concurrent · {policy.effective_limits.daily_cost_limit ?? "∞"} units/day</p>{policy.temporary_override_expires_at && new Date(policy.temporary_override_expires_at) > new Date() ? <p className="text-amber-700">temporary until {new Date(policy.temporary_override_expires_at).toLocaleString()}</p> : null}</td>
                <td className="px-4 py-3"><p>{(policy.utilization * 100).toFixed(0)}%</p><p className="text-xs text-slate-500">{policy.usage.daily_calls} calls · {policy.usage.daily_cost.toFixed(1)} units</p></td>
                <td className="px-4 py-3"><Status policy={policy} /></td>
                <td className="px-4 py-3"><div className="flex flex-wrap gap-1"><Action label="Adjust" disabled={busy || !policy.enabled} onClick={() => void adjustPolicy(policy)} /><Action label={policy.frozen ? "Unfreeze" : "Freeze"} disabled={busy || !policy.enabled} onClick={() => void perform(() => updateMCPQuotaPolicy(policy, { frozen: !policy.frozen }), policy.frozen ? "Policy unfrozen." : "Policy frozen.")} /><Action label="Reset" disabled={busy || !policy.enabled} onClick={() => void perform(() => resetMCPQuotaPolicy(policy), "Usage window reset.")} /><Action label="Disable" disabled={busy || !policy.enabled} onClick={() => void perform(() => disableMCPQuotaPolicy(policy.id), "Policy disabled.")} /></div></td>
              </tr>)}</tbody>
            </table></div>
          </section>
          <Breakdowns overview={overview} />
          <RecentRejections overview={overview} />
          <p className="text-xs text-slate-500">Updated {new Date(overview.generated_at).toLocaleString()} · refreshes every 10 seconds</p>
        </>
      ) : null}
    </div>
  );
}

function Summary({ overview }: { overview: MCPQuotaOverview }) {
  const cards = [["Calls", overview.summary.calls], ["Cost units", overview.summary.cost_units.toFixed(1)], ["Rejected", overview.summary.rejections], ["Concurrency", overview.summary.active_concurrency], ["Delegated calls", overview.summary.delegated_user_calls]];
  return <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{cards.map(([label, value]) => <article key={label} className="rounded-lg border border-border bg-white p-4"><p className="text-xs uppercase text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></article>)}</section>;
}

function Breakdowns({ overview }: { overview: MCPQuotaOverview }) {
  return <section className="grid gap-4 md:grid-cols-3"><Rank title="By server" items={overview.per_server} /><Rank title="By tool" items={overview.per_tool} /><Rank title="By principal" items={overview.per_principal} /></section>;
}

function Rank({ title, items }: { title: string; items: Array<[string, number]> }) {
  return <article className="rounded-lg border border-border bg-white p-5"><h2 className="font-semibold">{title}</h2><div className="mt-3 space-y-2">{items.slice(0, 10).map(([name, count]) => <div key={name} className="flex justify-between gap-3 text-sm"><span className="truncate">{name}</span><span>{count}</span></div>)}</div></article>;
}

function RecentRejections({ overview }: { overview: MCPQuotaOverview }) {
  return <section className="rounded-lg border border-border bg-white p-5"><h2 className="font-semibold">Recent rejections</h2><div className="mt-3 space-y-2">{overview.recent_rejections.map((item) => <div key={item.id} className="rounded border border-border p-3 text-sm"><span className="font-medium">{item.server_name}.{item.tool_name}</span> · {item.reason}<span className="ml-2 text-xs text-slate-500">{item.principal} · {new Date(item.created_at).toLocaleString()}</span></div>)}{!overview.recent_rejections.length ? <p className="text-sm text-emerald-700">No quota rejections.</p> : null}</div></section>;
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
