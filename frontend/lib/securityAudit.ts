import { appendFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import "server-only";

import type { AdminRole, AdminSessionState, AdminUser } from "./adminSession";

export type SecurityAuditOutcome = "success" | "failure" | "blocked";

export type SecurityAuditActor = {
  provider: AdminUser["provider"] | "unknown";
  login: string;
  role: AdminRole | null;
};

export type SecurityAuditEvent = {
  eventType: string;
  outcome: SecurityAuditOutcome;
  actor?: SecurityAuditActor;
  method?: string;
  path?: string;
  status?: number;
  reason?: string;
  ip?: string | null;
  userAgent?: string | null;
  metadata?: Record<string, string | number | boolean | null>;
};

export type SecurityAuditRecord = SecurityAuditEvent & {
  id: string;
  timestamp: string;
};

export async function auditSecurityEvent(event: SecurityAuditEvent): Promise<void> {
  const record = {
    id: randomUUID(),
    timestamp: new Date().toISOString(),
    ...event
  };
  try {
    const path = auditLogPath();
    await mkdir(dirname(path), { recursive: true });
    await appendFile(path, `${JSON.stringify(record)}\n`, "utf-8");
  } catch (error) {
    console.error("写入安全审计事件失败", error);
  }
  const ingestUrl = process.env.SECURITY_AUDIT_INGEST_URL;
  const ingestToken = process.env.SECURITY_AUDIT_INGEST_TOKEN;
  if (!ingestUrl) {
    return;
  }
  try {
    const response = await fetch(ingestUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ingestToken ?? ""}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(record),
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`审计接收端返回 ${response.status}`);
    }
  } catch (error) {
    console.error("投递前端安全审计事件失败", error);
    if (process.env.SECURITY_AUDIT_FAIL_CLOSED === "true") {
      throw error;
    }
  }
}

export async function readSecurityAuditEvents(limit = 100): Promise<SecurityAuditRecord[]> {
  try {
    const path = auditLogPath();
    const { readFile } = await import("node:fs/promises");
    const content = await readFile(path, "utf-8");
    return content
      .split("\n")
      .filter(Boolean)
      .slice(-Math.max(1, Math.min(limit, 500)))
      .reverse()
      .map((line) => JSON.parse(line) as SecurityAuditRecord);
  } catch (error) {
    if (isMissingFileError(error)) {
      return [];
    }
    console.error("读取安全审计事件失败", error);
    return [];
  }
}

export function requestAuditFields(request: Request): Pick<SecurityAuditEvent, "ip" | "userAgent"> {
  const forwardedFor = request.headers.get("x-forwarded-for");
  const realIp = request.headers.get("x-real-ip");
  return {
    ip: forwardedFor?.split(",")[0]?.trim() || realIp || null,
    userAgent: request.headers.get("user-agent")
  };
}

export function actorFromSession(state: AdminSessionState): SecurityAuditActor {
  return {
    provider: state.user?.provider ?? "unknown",
    login: state.user?.login ?? "anonymous",
    role: state.role
  };
}

export function actorFromUser(user: AdminUser, role: AdminRole | null): SecurityAuditActor {
  return {
    provider: user.provider,
    login: user.login,
    role
  };
}

function auditLogPath(): string {
  return resolve(process.env.SECURITY_AUDIT_LOG_PATH || "artifacts/security/events.jsonl");
}

function isMissingFileError(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === "object" &&
      "code" in error &&
      (error as { code?: string }).code === "ENOENT"
  );
}
