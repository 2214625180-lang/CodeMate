"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  assignRepositoryToMCPTenant,
  bindMCPTenantServer,
  configureMCPDelegatedProvider,
  createMCPAccessGrant,
  createMCPTenant,
  createMCPTenantMembership,
  deleteMCPAccessGrant,
  listMCPAccessGrants,
  listMCPDelegatedIdentities,
  listMCPDelegatedProviders,
  listMCPTenantBindings,
  listMCPTenantMemberships,
  listMCPTenants,
  revokeMCPDelegatedIdentity,
  rotateMCPTenantClientToken,
  startMCPDelegatedAuthorization
} from "@/lib/api";
import type {
  MCPAccessGrant,
  MCPDelegatedIdentity,
  MCPDelegatedProvider,
  MCPTenant,
  MCPTenantBinding,
  MCPTenantMembership
} from "@/lib/types";

export default function MCPTenancyPage() {
  const [tenants, setTenants] = useState<MCPTenant[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [memberships, setMemberships] = useState<MCPTenantMembership[]>([]);
  const [bindings, setBindings] = useState<MCPTenantBinding[]>([]);
  const [grants, setGrants] = useState<MCPAccessGrant[]>([]);
  const [providers, setProviders] = useState<MCPDelegatedProvider[]>([]);
  const [identities, setIdentities] = useState<MCPDelegatedIdentity[]>([]);
  const [clientToken, setClientToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadTenants = useCallback(async () => {
    const items = await listMCPTenants();
    setTenants(items);
    setTenantId((current) => current ?? items[0]?.id ?? null);
  }, []);

  const loadTenant = useCallback(async (selectedId: string) => {
    const [nextMemberships, nextBindings, nextGrants, nextProviders, nextIdentities] =
      await Promise.all([
        listMCPTenantMemberships(selectedId),
        listMCPTenantBindings(selectedId),
        listMCPAccessGrants(selectedId),
        listMCPDelegatedProviders(selectedId),
        listMCPDelegatedIdentities(selectedId)
      ]);
    setMemberships(nextMemberships);
    setBindings(nextBindings);
    setGrants(nextGrants);
    setProviders(nextProviders);
    setIdentities(nextIdentities);
  }, []);

  useEffect(() => {
    void loadTenants().catch(showError);
  }, [loadTenants]);

  useEffect(() => {
    if (tenantId) void loadTenant(tenantId).catch(showError);
  }, [loadTenant, tenantId]);

  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setNotice(message);
      await loadTenants();
      if (tenantId) await loadTenant(tenantId);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  }

  function showError(err: unknown) {
    setError(err instanceof Error ? err.message : "MCP tenancy operation failed");
  }

  const selected = tenants.find((item) => item.id === tenantId) ?? null;

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium uppercase text-slate-500">MCP Control Plane</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-950">Tenant Authorization</h1>
        <p className="mt-2 text-sm text-slate-600">
          Default-deny server bindings, repository-aware grants and delegated user OAuth identities.
        </p>
      </header>
      {error ? <Notice tone="error">{error}</Notice> : null}
      {notice ? <Notice tone="info">{notice}</Notice> : null}
      {clientToken ? (
        <Notice tone="warning">
          Tenant client token (shown once): <code className="break-all">{clientToken}</code>
        </Notice>
      ) : null}

      <section className="grid gap-4 rounded-lg border border-border bg-white p-5 md:grid-cols-2">
        <div>
          <h2 className="font-semibold">Tenants</h2>
          <select
            className="mt-3 w-full rounded-md border border-border px-3 py-2 text-sm"
            value={tenantId ?? ""}
            onChange={(event) => {
              setTenantId(event.target.value || null);
              setClientToken(null);
            }}
          >
            <option value="">Select tenant</option>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>{tenant.name} ({tenant.slug})</option>
            ))}
          </select>
          {selected ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void perform(async () => {
                const response = await rotateMCPTenantClientToken(selected.id);
                setClientToken(response.client_token);
              }, "Tenant client token rotated. Update callers before leaving this page.")}
              className="mt-3 rounded-md border border-border px-3 py-2 text-sm font-medium"
            >
              Rotate client token
            </button>
          ) : null}
        </div>
        <SimpleForm
          title="Create tenant"
          fields={[["slug", "acme"], ["name", "Acme Engineering"]]}
          disabled={busy}
          onSubmit={(data) => perform(async () => {
            const created = await createMCPTenant(data.slug, data.name);
            setTenantId(created.id);
          }, "Tenant created.")}
        />
      </section>

      {selected ? (
        <>
          <section className="grid gap-4 md:grid-cols-3">
            <Panel title="Memberships" items={memberships.map((item) => `${item.provider}:${item.subject} · ${item.role}`)}>
              <SimpleForm
                fields={[["provider", "github"], ["subject", "alice"], ["role", "member"]]}
                disabled={busy}
                onSubmit={(data) => perform(
                  () => createMCPTenantMembership(selected.id, {
                    provider: data.provider,
                    subject: data.subject,
                    role: data.role as "admin" | "approver" | "member"
                  }),
                  "Tenant member added."
                )}
              />
            </Panel>
            <Panel title="Server bindings" items={bindings.map((item) => `${item.server_name} · ${item.enabled ? "enabled" : "disabled"}`)}>
              <SimpleForm
                fields={[["server_name", "docs"]]}
                disabled={busy}
                onSubmit={(data) => perform(
                  () => bindMCPTenantServer(selected.id, data.server_name),
                  "Server bound to tenant."
                )}
              />
            </Panel>
            <Panel title="Repository scope" items={[]}>
              <SimpleForm
                fields={[["repo_id", "Repository UUID"]]}
                disabled={busy}
                onSubmit={(data) => perform(
                  () => assignRepositoryToMCPTenant(selected.id, data.repo_id),
                  "Repository assigned to tenant."
                )}
              />
            </Panel>
          </section>

          <section className="rounded-lg border border-border bg-white p-5">
            <h2 className="font-semibold">Access grants</h2>
            <p className="mt-1 text-xs text-slate-500">Deny overrides allow; blank repo ID creates a tenant-wide grant.</p>
            <SimpleForm
              fields={[
                ["principal_type", "agent"], ["principal_id", "codemate-agent"],
                ["server_name", "docs"], ["tool_name", "search"],
                ["permissions", "discover,execute"], ["effect", "allow"], ["repo_id", ""]
              ]}
              disabled={busy}
              onSubmit={(data) => perform(
                () => createMCPAccessGrant(selected.id, {
                  principal_type: data.principal_type as MCPAccessGrant["principal_type"],
                  principal_id: data.principal_id,
                  server_name: data.server_name,
                  tool_name: data.tool_name,
                  permissions: data.permissions.split(",").map((item) => item.trim()) as MCPAccessGrant["permissions"],
                  effect: data.effect as MCPAccessGrant["effect"],
                  repo_id: data.repo_id || null,
                  expires_at: null
                }),
                "Grant created."
              )}
            />
            <div className="mt-4 space-y-2">
              {grants.map((grant) => (
                <div key={grant.id} className="flex items-center justify-between gap-3 rounded border border-border p-3 text-sm">
                  <span>{grant.effect.toUpperCase()} {grant.principal_type}:{grant.principal_id} → {grant.server_name}.{grant.tool_name} [{grant.permissions.join(", ")}]</span>
                  <button type="button" disabled={busy} onClick={() => void perform(() => deleteMCPAccessGrant(grant.id), "Grant deleted.")} className="text-red-700">Delete</button>
                </div>
              ))}
            </div>
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <Panel title="Delegated OAuth providers" items={providers.map((item) => `${item.server_name} · ${item.client_id}`)}>
              <SimpleForm
                fields={[
                  ["server_name", "docs"], ["authorization_url", "https://idp.example.com/oauth/authorize"],
                  ["token_url", "https://idp.example.com/oauth/token"], ["client_id", "codemate"],
                  ["client_secret", ""], ["scopes", "mcp.read"],
                  ["redirect_uri", "https://codemate.example.com/mcp-tenancy/oauth/callback"]
                ]}
                disabled={busy}
                onSubmit={(data) => perform(
                  () => configureMCPDelegatedProvider(selected.id, {
                    ...data,
                    client_secret: data.client_secret || null,
                    scopes: data.scopes.split(/[ ,]+/).filter(Boolean)
                  }),
                  "OAuth provider configured."
                )}
              />
              <div className="mt-3 flex flex-wrap gap-2">
                {providers.map((provider) => (
                  <button key={provider.id} type="button" disabled={busy} onClick={() => void perform(async () => {
                    const response = await startMCPDelegatedAuthorization(provider.id);
                    window.location.assign(response.authorization_url);
                  }, "Redirecting to identity provider.")} className="rounded border border-border px-3 py-1 text-xs">
                    Connect {provider.server_name}
                  </button>
                ))}
              </div>
            </Panel>
            <Panel title="Delegated identities" items={[]}>
              <div className="space-y-2">
                {identities.map((identity) => (
                  <div key={identity.id} className="rounded border border-border p-3 text-sm">
                    <div>{identity.subject_provider}:{identity.subject} → {identity.server_name}</div>
                    <div className="mt-1 text-xs text-slate-500">{identity.revoked ? "revoked" : `expires ${identity.expires_at ?? "unknown"}`}</div>
                    {!identity.revoked ? <button type="button" disabled={busy} onClick={() => void perform(() => revokeMCPDelegatedIdentity(identity.id), "Delegated identity revoked.")} className="mt-2 text-xs text-red-700">Revoke</button> : null}
                  </div>
                ))}
              </div>
            </Panel>
          </section>
        </>
      ) : null}
    </div>
  );
}

function Panel({ title, items, children }: { title: string; items: string[]; children: React.ReactNode }) {
  return <section className="rounded-lg border border-border bg-white p-5">
    <h2 className="font-semibold">{title}</h2>
    {items.length ? <ul className="my-3 space-y-1 text-sm text-slate-600">{items.map((item) => <li key={item}>{item}</li>)}</ul> : null}
    {children}
  </section>;
}

function SimpleForm({ title, fields, disabled, onSubmit }: {
  title?: string;
  fields: Array<[string, string]>;
  disabled: boolean;
  onSubmit: (data: Record<string, string>) => Promise<unknown>;
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>;
    await onSubmit(values);
  }
  return <form onSubmit={(event) => void submit(event)} className="space-y-2">
    {title ? <h2 className="font-semibold">{title}</h2> : null}
    {fields.map(([name, placeholder]) => <input key={name} name={name} required={placeholder !== ""} placeholder={placeholder || name} aria-label={name} className="w-full rounded-md border border-border px-3 py-2 text-sm" />)}
    <button type="submit" disabled={disabled} className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-400">Save</button>
  </form>;
}

function Notice({ tone, children }: { tone: "error" | "info" | "warning"; children: React.ReactNode }) {
  const color = tone === "error" ? "border-red-200 bg-red-50 text-red-800" : tone === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-blue-200 bg-blue-50 text-blue-800";
  return <div className={`rounded-md border p-3 text-sm ${color}`}>{children}</div>;
}
