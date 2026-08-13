import { createHmac, randomBytes } from "node:crypto";

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  ADMIN_SESSION_COOKIE,
  adminSessionState,
  backendEvaluationApiToken,
  backendProductApiToken,
  canAccessEvaluationProxy,
  canMutateEvaluation
} from "@/lib/adminSession";
import {
  actorFromSession,
  auditSecurityEvent,
  requestAuditFields
} from "@/lib/securityAudit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade"
]);

type RouteContext = {
  params: Promise<{
    path?: string[];
  }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyBackend(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyBackend(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyBackend(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyBackend(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyBackend(request, context);
}

async function proxyBackend(request: NextRequest, context: RouteContext) {
  const { path = [] } = await context.params;
  const backendPath = `/${path.map(encodeURIComponent).join("/")}`;
  const evaluationPath =
    isEvaluationPath(backendPath) ||
    isMCPApprovalPath(backendPath) ||
    isMCPExecutionPath(backendPath) ||
    isMCPOperationsPath(backendPath) ||
    isMCPRegistryPath(backendPath) ||
    isMCPTenancyPath(backendPath) ||
    isMCPQuotaPath(backendPath);
  const productPath = isProductPath(backendPath);
  const sessionState = evaluationPath || productPath
    ? adminSessionState((await cookies()).get(ADMIN_SESSION_COOKIE)?.value)
    : null;

  if (sessionState) {
    const state = sessionState;
    const eventNamespace = evaluationPath ? "evaluation" : "product";
    if (state.misconfigured) {
      await auditSecurityEvent({
        eventType: `${eventNamespace}_proxy_blocked`,
        outcome: "blocked",
        actor: actorFromSession(state),
        method: request.method,
        path: backendPath,
        status: 503,
        reason: state.detail ?? "misconfigured",
        ...requestAuditFields(request)
      });
      return NextResponse.json(
        {
          detail: state.detail ?? "CodeMate authentication is not configured correctly."
        },
        { status: 503 }
      );
    }
    if (!canAccessEvaluationProxy(state)) {
      await auditSecurityEvent({
        eventType: `${eventNamespace}_proxy_unauthenticated`,
        outcome: "blocked",
        actor: actorFromSession(state),
        method: request.method,
        path: backendPath,
        status: 401,
        reason: "session_required",
        ...requestAuditFields(request)
      });
      return NextResponse.json({ detail: "CodeMate session required" }, { status: 401 });
    }
    if (
      evaluationPath &&
      isEvaluationMutation(request.method) &&
      !isDelegatedAuthorizationStart(backendPath) &&
      !canMutateEvaluation(state)
    ) {
      await auditSecurityEvent({
        eventType: `${eventNamespace}_proxy_forbidden`,
        outcome: "blocked",
        actor: actorFromSession(state),
        method: request.method,
        path: backendPath,
        status: 403,
        reason: "admin_role_required",
        ...requestAuditFields(request)
      });
      return NextResponse.json({ detail: "Evaluation admin role required" }, { status: 403 });
    }
  }

  const targetUrl = new URL(`${backendBaseUrl()}${backendPath}`);
  targetUrl.search = request.nextUrl.search;

  const headers = new Headers();
  const accept = request.headers.get("accept");
  const contentType = request.headers.get("content-type");
  if (accept) {
    headers.set("accept", accept);
  }
  if (contentType) {
    headers.set("content-type", contentType);
  }

  const evaluationToken = backendEvaluationApiToken();
  if (evaluationPath) {
    headers.set("x-codemate-evaluation-client", "browser");
    if (evaluationToken) {
      headers.set("authorization", `Bearer ${evaluationToken}`);
    }
    if (sessionState?.role) {
      headers.set("x-codemate-evaluation-role", sessionState.role);
    }
    if (sessionState?.user) {
      headers.set("x-codemate-evaluation-user", sessionState.user.login);
      headers.set("x-codemate-evaluation-provider", sessionState.user.provider);
    }
    if (sessionState?.role && sessionState.user) {
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const nonce = randomBytes(24).toString("base64url");
      const pathWithQuery = `${backendPath}${request.nextUrl.search}`;
      headers.set("x-codemate-evaluation-identity-timestamp", timestamp);
      headers.set("x-codemate-evaluation-identity-nonce", nonce);
      headers.set(
        "x-codemate-evaluation-identity-signature",
        signEvaluationIdentity({
          method: request.method,
          pathWithQuery,
          timestamp,
          nonce,
          role: sessionState.role,
          login: sessionState.user.login,
          provider: sessionState.user.provider
        })
      );
    }
  }

  if (productPath) {
    const productToken = backendProductApiToken();
    if (productToken) {
      headers.set("authorization", `Bearer ${productToken}`);
    }
    if (sessionState?.user) {
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const nonce = randomBytes(24).toString("base64url");
      const pathWithQuery = `${backendPath}${request.nextUrl.search}`;
      headers.set("x-codemate-product-user", sessionState.user.login);
      headers.set("x-codemate-product-provider", sessionState.user.provider);
      headers.set("x-codemate-product-identity-timestamp", timestamp);
      headers.set("x-codemate-product-identity-nonce", nonce);
      headers.set(
        "x-codemate-product-identity-signature",
        signProductIdentity({
          method: request.method,
          pathWithQuery,
          timestamp,
          nonce,
          login: sessionState.user.login,
          provider: sessionState.user.provider
        })
      );
    }
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store"
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  const response = await fetch(targetUrl, init);
  if (sessionState) {
    await auditSecurityEvent({
      eventType: evaluationPath ? "evaluation_proxy_request" : "product_proxy_request",
      outcome: response.ok ? "success" : "failure",
      actor: actorFromSession(sessionState),
      method: request.method,
      path: backendPath,
      status: response.status,
      reason: response.ok ? undefined : "backend_response_not_ok",
      ...requestAuditFields(request)
    });
  }
  const responseHeaders = filteredResponseHeaders(response.headers);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders
  });
}

function isEvaluationPath(path: string): boolean {
  return path === "/evaluations" || path.startsWith("/evaluations/");
}

function isMCPApprovalPath(path: string): boolean {
  return path === "/mcp-approvals" || path.startsWith("/mcp-approvals/");
}

function isMCPExecutionPath(path: string): boolean {
  return path === "/mcp-executions" || path.startsWith("/mcp-executions/");
}

function isMCPOperationsPath(path: string): boolean {
  return path === "/mcp-operations" || path.startsWith("/mcp-operations/");
}

function isMCPRegistryPath(path: string): boolean {
  return path === "/mcp-registry" || path.startsWith("/mcp-registry/");
}

function isMCPTenancyPath(path: string): boolean {
  return path === "/mcp-tenancy" || path.startsWith("/mcp-tenancy/");
}

function isMCPQuotaPath(path: string): boolean {
  return path === "/mcp-quotas" || path.startsWith("/mcp-quotas/");
}

function isProductPath(path: string): boolean {
  return (
    path === "/repos" ||
    path.startsWith("/repos/") ||
    path.startsWith("/runs/") ||
    path === "/github-app" ||
    path.startsWith("/github-app/")
  );
}

function isDelegatedAuthorizationStart(path: string): boolean {
  return /^\/mcp-tenancy\/oauth\/providers\/[^/]+\/authorize$/.test(path);
}

function isEvaluationMutation(method: string): boolean {
  return method !== "GET" && method !== "HEAD";
}

function backendBaseUrl(): string {
  return (
    process.env.BACKEND_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000"
  ).replace(/\/+$/, "");
}

function signEvaluationIdentity({
  method,
  pathWithQuery,
  timestamp,
  nonce,
  role,
  login,
  provider
}: {
  method: string;
  pathWithQuery: string;
  timestamp: string;
  nonce: string;
  role: "admin" | "viewer";
  login: string;
  provider: string;
}): string {
  const payload = [
    "v1",
    timestamp.trim(),
    nonce.trim(),
    method.toUpperCase(),
    pathWithQuery,
    role.trim().toLowerCase(),
    login.trim(),
    provider.trim()
  ].join("\n");
  return createHmac("sha256", proxyIdentitySecret()).update(payload).digest("base64url");
}

function proxyIdentitySecret(): string {
  return (
    process.env.CODEMATE_PROXY_IDENTITY_CURRENT_SECRET ||
    process.env.CODEMATE_PROXY_IDENTITY_SECRET ||
    process.env.PROXY_IDENTITY_SECRET ||
    backendEvaluationApiToken()
  ).trim();
}

function signProductIdentity({
  method,
  pathWithQuery,
  timestamp,
  nonce,
  login,
  provider
}: {
  method: string;
  pathWithQuery: string;
  timestamp: string;
  nonce: string;
  login: string;
  provider: string;
}): string {
  const payload = [
    "v1",
    timestamp.trim(),
    nonce.trim(),
    method.toUpperCase(),
    pathWithQuery,
    login.trim(),
    provider.trim()
  ].join("\n");
  return createHmac("sha256", productIdentitySecret()).update(payload).digest("base64url");
}

function productIdentitySecret(): string {
  return (
    process.env.CODEMATE_PRODUCT_IDENTITY_SECRET ||
    process.env.PRODUCT_IDENTITY_SECRET ||
    backendProductApiToken()
  ).trim();
}

function filteredResponseHeaders(headers: Headers): Headers {
  const filtered = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      filtered.set(key, value);
    }
  });
  return filtered;
}
