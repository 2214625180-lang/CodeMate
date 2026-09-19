"use client";

import { FormEvent, ReactNode, useEffect, useState } from "react";
import Link from "next/link";

type SessionState = {
  authRequired: boolean;
  authenticated: boolean;
  misconfigured: boolean;
  authMode: "open" | "github" | "password" | "misconfigured";
  role: "admin" | "viewer" | null;
  user: {
    provider: "github" | "password" | "local";
    login: string;
    name: string | null;
    avatarUrl: string | null;
  } | null;
  detail?: string;
};

export function EvaluationAdminGate({
  children,
  label = "评测中心"
}: {
  children: ReactNode;
  label?: string;
}) {
  const [state, setState] = useState<SessionState | null>(null);
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const authError = new URLSearchParams(window.location.search).get("auth_error");
    if (authError) {
      setError(authError);
    }
    void loadSession();
  }, []);

  async function loadSession() {
    try {
      const response = await fetch("/api/admin/session", { cache: "no-store" });
      const data = (await response.json()) as SessionState;
      setState(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "检查管理员会话失败");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/admin/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
      });
      const data = (await response.json().catch(() => ({}))) as SessionState & {
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(data.detail || `登录失败，状态码：${response.status}`);
      }
      setPassword("");
      setState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : `解锁失败：${label}`);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function signOut() {
    await fetch("/api/admin/session", { method: "DELETE" });
    await loadSession();
  }

  if (!state) {
    return (
      <section className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
        正在加载 {label}...
      </section>
    );
  }

  if (state.misconfigured) {
    return (
      <section className="rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
        <h1 className="text-base font-semibold text-amber-950">{label} 尚未配置管理员</h1>
        <p className="mt-2">{state.detail ?? "请检查前端身份验证环境配置。"}</p>
      </section>
    );
  }

  if (state.authRequired && !state.authenticated) {
    if (state.authMode === "github") {
      return (
        <section className="mx-auto max-w-md rounded-lg border border-border bg-white p-5">
          <h1 className="text-lg font-semibold text-slate-950">{label} 管理员</h1>
          <p className="mt-2 text-sm text-slate-600">
            请使用 GitHub 登录以继续。
          </p>
          {error ? <p className="mt-4 text-sm text-red-700">{error}</p> : null}
          <a
            href="/api/auth/github/start"
            className="mt-5 block rounded-md bg-slate-950 px-3 py-2 text-center text-sm font-medium text-white hover:bg-slate-800"
          >
            使用 GitHub 登录
          </a>
        </section>
      );
    }

    return (
      <section className="mx-auto max-w-md rounded-lg border border-border bg-white p-5">
        <h1 className="text-lg font-semibold text-slate-950">{label} 管理员</h1>
        <form className="mt-5 space-y-4" onSubmit={submit}>
          <div>
            <label htmlFor="evaluation-admin-password" className="text-sm font-medium text-slate-700">
              管理员密码
            </label>
            <input
              id="evaluation-admin-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
              autoComplete="current-password"
            />
          </div>
          {error ? <p className="text-sm text-red-700">{error}</p> : null}
          <button
            type="submit"
            disabled={isSubmitting || !password}
            className="w-full rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isSubmitting ? "正在解锁…" : "解锁"}
          </button>
        </form>
      </section>
    );
  }

  return (
    <>
      {state.authRequired ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-white px-4 py-3 text-sm text-slate-600">
          <span>
            {state.user?.login ?? "评测用户"} · {state.role ?? "viewer"}
          </span>
          <div className="flex flex-wrap gap-2">
            {state.role === "admin" ? (
              <Link
                href="/evaluations/security"
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                安全日志
              </Link>
            ) : null}
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              退出登录
            </button>
          </div>
        </div>
      ) : null}
      {children}
    </>
  );
}
