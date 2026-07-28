import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  ADMIN_SESSION_COOKIE,
  adminSessionState,
  canAccessEvaluationProxy,
  canMutateEvaluation
} from "@/lib/adminSession";
import {
  actorFromSession,
  auditSecurityEvent,
  readSecurityAuditEvents,
  requestAuditFields
} from "@/lib/securityAudit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const state = adminSessionState((await cookies()).get(ADMIN_SESSION_COOKIE)?.value);
  const path = request.nextUrl.pathname;
  if (state.misconfigured) {
    await auditSecurityEvent({
      eventType: "security_audit_read_blocked",
      outcome: "blocked",
      actor: actorFromSession(state),
      method: request.method,
      path,
      status: 503,
      reason: state.detail ?? "misconfigured",
      ...requestAuditFields(request)
    });
    return NextResponse.json(
      { detail: state.detail ?? "Evaluation authentication is not configured correctly." },
      { status: 503 }
    );
  }
  if (!canAccessEvaluationProxy(state)) {
    await auditSecurityEvent({
      eventType: "security_audit_read_blocked",
      outcome: "blocked",
      actor: actorFromSession(state),
      method: request.method,
      path,
      status: 401,
      reason: "session_required",
      ...requestAuditFields(request)
    });
    return NextResponse.json({ detail: "Evaluation session required" }, { status: 401 });
  }
  if (!canMutateEvaluation(state)) {
    await auditSecurityEvent({
      eventType: "security_audit_read_blocked",
      outcome: "blocked",
      actor: actorFromSession(state),
      method: request.method,
      path,
      status: 403,
      reason: "admin_role_required",
      ...requestAuditFields(request)
    });
    return NextResponse.json({ detail: "Evaluation admin role required" }, { status: 403 });
  }

  const limit = Number(request.nextUrl.searchParams.get("limit") || "100");
  const events = await readSecurityAuditEvents(Number.isFinite(limit) ? limit : 100);
  await auditSecurityEvent({
    eventType: "security_audit_read",
    outcome: "success",
    actor: actorFromSession(state),
    method: request.method,
    path,
    status: 200,
    metadata: {
      returnedEvents: events.length
    },
    ...requestAuditFields(request)
  });
  return NextResponse.json({ events });
}
