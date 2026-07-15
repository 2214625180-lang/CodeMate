import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  ADMIN_SESSION_COOKIE,
  GITHUB_OAUTH_STATE_COOKIE,
  adminCookieOptions,
  createAdminSessionValue,
  githubOAuthConfig,
  oauthStateCookieOptions,
  resolveGitHubRole
} from "@/lib/adminSession";
import { exchangeGitHubCode, fetchGitHubIdentity } from "@/lib/githubOAuth";
import { actorFromUser, auditSecurityEvent, requestAuditFields } from "@/lib/securityAudit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const config = githubOAuthConfig();
  if (!config) {
    await auditSecurityEvent({
      eventType: "github_oauth_callback_failed",
      outcome: "failure",
      method: request.method,
      path: request.nextUrl.pathname,
      status: 503,
      reason: "github_oauth_not_configured",
      ...requestAuditFields(request)
    });
    return redirectWithError(request, "GitHub OAuth is not configured");
  }

  const url = request.nextUrl;
  const oauthError = url.searchParams.get("error");
  if (oauthError) {
    await auditSecurityEvent({
      eventType: "github_oauth_callback_failed",
      outcome: "failure",
      method: request.method,
      path: request.nextUrl.pathname,
      status: 401,
      reason: oauthError,
      ...requestAuditFields(request)
    });
    return redirectWithError(request, "GitHub OAuth was not authorized");
  }

  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const expectedState = (await cookies()).get(GITHUB_OAUTH_STATE_COOKIE)?.value;
  if (!code || !state || !expectedState || state !== expectedState) {
    await auditSecurityEvent({
      eventType: "github_oauth_callback_failed",
      outcome: "failure",
      method: request.method,
      path: request.nextUrl.pathname,
      status: 401,
      reason: "invalid_oauth_state",
      ...requestAuditFields(request)
    });
    return redirectWithError(request, "Invalid GitHub OAuth state");
  }

  try {
    const redirectUri = config.redirectUri || new URL("/api/auth/github/callback", request.url).toString();
    const accessToken = await exchangeGitHubCode(config, code, redirectUri);
    const identity = await fetchGitHubIdentity(accessToken);
    const role = resolveGitHubRole(identity);
    if (!role) {
      await auditSecurityEvent({
        eventType: "github_oauth_rbac_denied",
        outcome: "blocked",
        actor: {
          provider: "github",
          login: identity.login,
          role: null
        },
        method: request.method,
        path: request.nextUrl.pathname,
        status: 403,
        reason: "rbac_no_match",
        metadata: {
          orgCount: identity.orgs.length,
          teamCount: identity.teams.length
        },
        ...requestAuditFields(request)
      });
      return redirectWithError(request, "Your GitHub account is not allowed to access CodeMate evaluations");
    }

    await auditSecurityEvent({
      eventType: "github_oauth_login_succeeded",
      outcome: "success",
      actor: actorFromUser(
        {
          provider: "github",
          login: identity.login,
          name: identity.name,
          avatarUrl: identity.avatarUrl
        },
        role
      ),
      method: request.method,
      path: request.nextUrl.pathname,
      status: 302,
      metadata: {
        orgCount: identity.orgs.length,
        teamCount: identity.teams.length
      },
      ...requestAuditFields(request)
    });

    const response = NextResponse.redirect(new URL("/evaluations", request.url));
    response.cookies.set(
      ADMIN_SESSION_COOKIE,
      createAdminSessionValue(role, {
        provider: "github",
        login: identity.login,
        name: identity.name,
        avatarUrl: identity.avatarUrl
      }),
      adminCookieOptions()
    );
    response.cookies.set(GITHUB_OAUTH_STATE_COOKIE, "", {
      ...oauthStateCookieOptions(),
      maxAge: 0
    });
    return response;
  } catch (error) {
    await auditSecurityEvent({
      eventType: "github_oauth_callback_failed",
      outcome: "failure",
      method: request.method,
      path: request.nextUrl.pathname,
      status: 500,
      reason: error instanceof Error ? error.message : "github_oauth_login_failed",
      ...requestAuditFields(request)
    });
    return redirectWithError(
      request,
      error instanceof Error ? error.message : "GitHub OAuth login failed"
    );
  }
}

function redirectWithError(request: NextRequest, message: string) {
  const response = NextResponse.redirect(
    new URL(`/evaluations?auth_error=${encodeURIComponent(message)}`, request.url)
  );
  response.cookies.set(GITHUB_OAUTH_STATE_COOKIE, "", {
    ...oauthStateCookieOptions(),
    maxAge: 0
  });
  return response;
}
