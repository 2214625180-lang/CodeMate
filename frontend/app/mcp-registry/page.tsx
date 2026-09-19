"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createMCPRegistryServer,
  deleteMCPRegistryCredential,
  deleteMCPRegistryServer,
  listMCPRegistryRevisions,
  listMCPRegistryServers,
  restoreMCPRegistryRevision,
  setMCPRegistryCredential,
  updateMCPRegistryServer,
  validateMCPRegistryServer
} from "@/lib/api";
import type { MCPRegistryRevision, MCPRegistryServer } from "@/lib/types";

export default function MCPRegistryPage() {
  const [servers, setServers] = useState<MCPRegistryServer[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<MCPRegistryRevision[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listMCPRegistryServers();
      setServers(data);
      setSelectedId((current) => current ?? data[0]?.id ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 MCP 注册信息失败");
    }
  }, []);

  useEffect(() => void load(), [load]);
  const selected = servers.find((item) => item.id === selectedId) ?? null;

  useEffect(() => {
    if (!selectedId) {
      setRevisions([]);
      return;
    }
    void listMCPRegistryRevisions(selectedId)
      .then(setRevisions)
      .catch((err) => setError(err instanceof Error ? err.message : "加载配置版本失败"));
  }, [selectedId, servers]);

  async function perform(name: string, fn: () => Promise<unknown>, message: string) {
    setBusy(name);
    setError(null);
    try {
      await fn();
      setNotice(message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册管理操作失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium uppercase text-slate-500">MCP 控制平面</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-950">动态服务注册</h1>
        <p className="mt-2 text-sm text-slate-600">
          支持服务配置热加载、凭据加密、验证快照和版本回滚。
        </p>
      </header>
      {error ? <Message tone="error">{error}</Message> : null}
      {notice ? <Message tone="info">{notice}</Message> : null}
      <CreateServerForm
        disabled={busy !== null}
        onCreate={(payload) =>
          perform(
            "create",
            async () => {
              const created = await createMCPRegistryServer(payload);
              setSelectedId(created.id);
            },
            "服务已注册，配置无需重启即可生效。"
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <section className="rounded-lg border border-border bg-white p-4">
          <h2 className="font-semibold text-slate-950">已注册服务</h2>
          <div className="mt-3 space-y-2">
            {servers.map((server) => (
              <button
                key={server.id}
                type="button"
                onClick={() => setSelectedId(server.id)}
                className={`w-full rounded-md border p-3 text-left ${
                  selectedId === server.id ? "border-slate-950 bg-slate-50" : "border-border"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-950">{server.name}</span>
                  <Status value={server.validation_status} />
                </div>
                <p className="mt-1 truncate text-xs text-slate-500">{server.url}</p>
              </button>
            ))}
            {!servers.length ? <p className="text-sm text-slate-500">暂无动态服务。</p> : null}
          </div>
        </section>
        {selected ? (
          <div className="space-y-4">
            <ServerDetails
              server={selected}
              busy={busy}
              onAction={(name, fn, message) => void perform(name, fn, message)}
              onDeleted={() => setSelectedId(null)}
            />
            <CredentialPanel
              server={selected}
              busy={busy}
              onAction={(name, fn, message) => void perform(name, fn, message)}
            />
            <RevisionPanel
              server={selected}
              revisions={revisions}
              busy={busy}
              onRestore={(revision) =>
                void perform(
                  `restore:${revision.id}`,
                  () => restoreMCPRegistryRevision(selected, revision.id),
                  `已恢复配置版本 ${revision.version}.`
                )
              }
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

type CreatePayload = Parameters<typeof createMCPRegistryServer>[0];

function CreateServerForm({
  disabled,
  onCreate
}: {
  disabled: boolean;
  onCreate: (payload: CreatePayload) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [tools, setTools] = useState("");
  const [policies, setPolicies] = useState("{}");
  const [idempotencyMode, setIdempotencyMode] = useState<"none" | "metadata">("none");

  function submit(event: FormEvent) {
    event.preventDefault();
    const allowedTools = tools.split(",").map((item) => item.trim()).filter(Boolean);
    try {
      const parsed = JSON.parse(policies) as CreatePayload["tool_policies"];
      onCreate({
        name: name.trim(),
        url: url.trim(),
        enabled: true,
        allowed_tools: allowedTools,
        tool_policies: parsed,
        idempotency_mode: idempotencyMode
      });
    } catch {
      window.alert("工具策略必须是有效的 JSON。");
    }
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-border bg-white p-5">
      <h2 className="font-semibold text-slate-950">注册服务</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-5">
        <Input label="名称" value={name} onChange={setName} placeholder="tracker" />
        <Input label="HTTPS 接口地址" value={url} onChange={setUrl} placeholder="https://mcp.example/mcp" />
        <Input label="允许的工具" value={tools} onChange={setTools} placeholder="search,update" />
        <Input label="策略 JSON" value={policies} onChange={setPolicies} placeholder='{"search":"auto"}' />
        <label className="text-sm text-slate-700">幂等机制
          <select value={idempotencyMode} onChange={(event) => setIdempotencyMode(event.target.value as "none" | "metadata")} className="mt-1 block w-full rounded-md border border-border px-3 py-2">
            <option value="none">none</option><option value="metadata">metadata</option>
          </select>
        </label>
      </div>
      <button type="submit" disabled={disabled || !name || !url} className="mt-4 rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-400">注册</button>
    </form>
  );
}

function ServerDetails({ server, busy, onAction, onDeleted }: { server: MCPRegistryServer; busy: string | null; onAction: (name: string, fn: () => Promise<unknown>, message: string) => void; onDeleted: () => void }) {
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-lg font-semibold text-slate-950">{server.name}</h2><p className="mt-1 text-sm text-slate-500">{server.url}</p></div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy !== null} onClick={() => onAction("toggle", () => updateMCPRegistryServer(server, { enabled: !server.enabled }), server.enabled ? "服务已禁用。" : "服务已启用。")}>{server.enabled ? "禁用" : "启用"}</Button>
          <Button disabled={busy !== null} onClick={() => onAction("validate", () => validateMCPRegistryServer(server.id), "验证已完成。")}>验证</Button>
          <Button disabled={busy !== null} onClick={() => onAction("delete", async () => { await deleteMCPRegistryServer(server); onDeleted(); }, "服务已删除。")}>删除</Button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <p>状态： <Status value={server.validation_status} /></p>
        <p>协议： {server.protocol_version ?? "—"}</p>
        <p>版本： {server.version}</p>
        <p>工具： {server.allowed_tools.join(", ") || "none"}</p>
        <p>幂等机制： {server.idempotency_mode}</p>
        <p>更新者： {server.updated_by ?? "—"}</p>
      </div>
      {server.validation_error ? <p className="mt-3 rounded bg-red-50 p-3 text-sm text-red-700">{server.validation_error}</p> : null}
      {server.tools_snapshot ? <details className="mt-4"><summary className="cursor-pointer text-sm font-medium">能力与工具快照</summary><pre className="mt-2 max-h-72 overflow-auto rounded bg-panel p-3 text-xs">{JSON.stringify({ capabilities: server.capabilities, tools: server.tools_snapshot }, null, 2)}</pre></details> : null}
    </section>
  );
}

function CredentialPanel({ server, busy, onAction }: { server: MCPRegistryServer; busy: string | null; onAction: (name: string, fn: () => Promise<unknown>, message: string) => void }) {
  const [type, setType] = useState<"bearer" | "oauth2_client_credentials">("bearer");
  const [token, setToken] = useState("");
  const [tokenUrl, setTokenUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  function save() {
    const payload = type === "bearer" ? { auth_type: type, token, expected_version: server.credential?.version } : { auth_type: type, token_url: tokenUrl, client_id: clientId, client_secret: clientSecret, scopes: [], expected_version: server.credential?.version };
    onAction("credential", () => setMCPRegistryCredential(server.id, payload), "凭据已加密并保存。");
    setToken(""); setClientSecret("");
  }
  return (
    <section className="rounded-lg border border-border bg-white p-5">
      <div className="flex items-center justify-between"><h2 className="font-semibold text-slate-950">凭据代理</h2><span className="text-sm text-slate-500">{server.credential ? `${server.credential.auth_type} · ${server.credential.encryption_provider}` : "无凭据"}</span></div>
      <select value={type} onChange={(event) => setType(event.target.value as typeof type)} className="mt-4 rounded-md border border-border px-3 py-2 text-sm"><option value="bearer">Bearer 令牌</option><option value="oauth2_client_credentials">OAuth2 客户端凭据</option></select>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        {type === "bearer" ? <Input label="新令牌" value={token} onChange={setToken} secret /> : <><Input label="令牌地址" value={tokenUrl} onChange={setTokenUrl} /><Input label="客户端 ID" value={clientId} onChange={setClientId} /><Input label="客户端密钥" value={clientSecret} onChange={setClientSecret} secret /></>}
      </div>
      <div className="mt-3 flex gap-2"><Button disabled={busy !== null || (type === "bearer" ? !token : !tokenUrl || !clientId || !clientSecret)} onClick={save}>保存凭据</Button>{server.credential ? <Button disabled={busy !== null} onClick={() => onAction("credential-delete", () => deleteMCPRegistryCredential(server.id), "凭据已删除。")}>删除凭据</Button> : null}</div>
      <p className="mt-3 text-xs text-slate-500">密钥采用独立的信封加密，API 和浏览器代理均不会返回密钥原文。{server.credential ? ` KMS 密钥：${server.credential.kms_key_id}` : ""}</p>
    </section>
  );
}

function RevisionPanel({ server, revisions, busy, onRestore }: { server: MCPRegistryServer; revisions: MCPRegistryRevision[]; busy: string | null; onRestore: (revision: MCPRegistryRevision) => void }) {
  return <section className="rounded-lg border border-border bg-white p-5"><h2 className="font-semibold text-slate-950">配置历史</h2><div className="mt-3 space-y-2">{revisions.map((revision) => <div key={revision.id} className="flex items-center justify-between rounded border border-border p-3 text-sm"><div><span className="font-medium">v{revision.version} · {revision.action}</span><p className="text-xs text-slate-500">{revision.actor} · {new Date(revision.created_at).toLocaleString()}</p></div><Button disabled={busy !== null || revision.version === server.version} onClick={() => onRestore(revision)}>恢复</Button></div>)}</div></section>;
}

function Input({ label, value, onChange, placeholder, secret = false }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; secret?: boolean }) { return <label className="text-sm text-slate-700">{label}<input type={secret ? "password" : "text"} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1 block w-full rounded-md border border-border px-3 py-2" /></label>; }
function Button({ children, disabled, onClick }: { children: React.ReactNode; disabled: boolean; onClick: () => void }) { return <button type="button" disabled={disabled} onClick={onClick} className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-400">{children}</button>; }
function Status({ value }: { value: string }) { const good = value === "valid"; const bad = value === "invalid"; return <span className={`rounded-full px-2 py-1 text-xs ${good ? "bg-emerald-50 text-emerald-700" : bad ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{value}</span>; }
function Message({ children, tone }: { children: React.ReactNode; tone: "error" | "info" }) { return <div className={`rounded-md p-3 text-sm ${tone === "error" ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-700"}`}>{children}</div>; }
