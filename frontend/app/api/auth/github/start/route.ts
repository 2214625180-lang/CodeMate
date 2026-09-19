import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  GITHUB_OAUTH_STATE_COOKIE,
  createOAuthState,
  githubOAuthConfig,
  oauthStateCookieOptions
} from "@/lib/adminSession";
import { githubAuthorizeUrl } from "@/lib/githubOAuth";
import { auditSecurityEvent, requestAuditFields } from "@/lib/securityAudit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const config = githubOAuthConfig();
  if (!config) {
    await auditSecurityEvent({
      eventType: "github_oauth_start_failed",
      outcome: "failure",
      method: request.method,
      path: request.nextUrl.pathname,
      status: 503,
      reason: "github_oauth_not_configured",
      ...requestAuditFields(request)
    });
    return NextResponse.json({ detail: "尚未配置 GitHub OAuth" }, { status: 503 });
  }

  const state = createOAuthState();
  const redirectUri = githubRedirectUri(request, config.redirectUri);
  await auditSecurityEvent({
    eventType: "github_oauth_started",
    outcome: "success",
    method: request.method,
    path: request.nextUrl.pathname,
    status: 302,
    ...requestAuditFields(request)
  });
  const response = NextResponse.redirect(githubAuthorizeUrl(config, redirectUri, state));
  response.cookies.set(GITHUB_OAUTH_STATE_COOKIE, state, oauthStateCookieOptions());
  return response;
}

function githubRedirectUri(request: NextRequest, configuredRedirectUri: string | null): string {
  return configuredRedirectUri || new URL("/api/auth/github/callback", request.url).toString();
}
