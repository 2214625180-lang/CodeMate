import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  ADMIN_SESSION_COOKIE,
  adminCookieOptions,
  adminSessionState,
  createAdminSessionValue,
  verifyFrontendAdminPassword
} from "@/lib/adminSession";
import {
  actorFromSession,
  auditSecurityEvent,
  requestAuditFields
} from "@/lib/securityAudit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const state = adminSessionState((await cookies()).get(ADMIN_SESSION_COOKIE)?.value);
  return NextResponse.json(state);
}

export async function POST(request: NextRequest) {
  const state = adminSessionState((await cookies()).get(ADMIN_SESSION_COOKIE)?.value);
  if (!state.authRequired) {
    return NextResponse.json(state);
  }
  if (state.misconfigured) {
    await auditSecurityEvent({
      eventType: "password_login_blocked",
      outcome: "blocked",
      actor: actorFromSession(state),
      method: request.method,
      path: request.nextUrl.pathname,
      status: 503,
      reason: state.detail ?? "misconfigured",
      ...requestAuditFields(request)
    });
    return NextResponse.json(
      {
        ...state,
        detail: state.detail ?? "Evaluation authentication is not configured correctly."
      },
      { status: 503 }
    );
  }

  const payload = (await request.json().catch(() => ({}))) as { password?: string };
  if (!verifyFrontendAdminPassword(payload.password ?? "")) {
    await auditSecurityEvent({
      eventType: "password_login_failed",
      outcome: "failure",
      actor: actorFromSession(state),
      method: request.method,
      path: request.nextUrl.pathname,
      status: 401,
      reason: "invalid_password",
      ...requestAuditFields(request)
    });
    return NextResponse.json({ detail: "Invalid admin password" }, { status: 401 });
  }

  await auditSecurityEvent({
    eventType: "password_login_succeeded",
    outcome: "success",
    actor: {
      provider: "password",
      login: "password-admin",
      role: "admin"
    },
    method: request.method,
    path: request.nextUrl.pathname,
    status: 200,
    ...requestAuditFields(request)
  });

  const response = NextResponse.json({
    authRequired: true,
    authenticated: true,
    misconfigured: false,
    authMode: "password",
    role: "admin",
    user: {
      provider: "password",
      login: "password-admin",
      name: "Password Admin",
      avatarUrl: null
    }
  });
  response.cookies.set(ADMIN_SESSION_COOKIE, createAdminSessionValue(), adminCookieOptions());
  return response;
}

export async function DELETE(request: NextRequest) {
  const state = adminSessionState(undefined);
  const currentState = adminSessionState((await cookies()).get(ADMIN_SESSION_COOKIE)?.value);
  await auditSecurityEvent({
    eventType: "logout",
    outcome: "success",
    actor: actorFromSession(currentState),
    method: request.method,
    path: request.nextUrl.pathname,
    status: 200,
    ...requestAuditFields(request)
  });
  const response = NextResponse.json({
    authRequired: Boolean(state.authRequired),
    authenticated: false,
    misconfigured: state.misconfigured,
    authMode: state.authMode,
    role: null,
    user: null
  });
  response.cookies.set(ADMIN_SESSION_COOKIE, "", {
    ...adminCookieOptions(),
    maxAge: 0
  });
  return response;
}
