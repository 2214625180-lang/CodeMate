import { createHmac } from "node:crypto";

import { afterEach, describe, expect, it } from "vitest";

import {
  adminSessionState,
  createAdminSessionValue,
  parseAdminSession
} from "@/lib/adminSession";

const AUTH_ENV_KEYS = [
  "CODEMATE_EVALUATION_API_TOKEN",
  "EVALUATION_ADMIN_TOKEN",
  "CODEMATE_PRODUCT_API_TOKEN",
  "PRODUCT_API_TOKEN",
  "FRONTEND_ADMIN_PASSWORD",
  "CODEMATE_FRONTEND_ADMIN_PASSWORD",
  "FRONTEND_ADMIN_SESSION_SECRET",
  "CODEMATE_FRONTEND_SESSION_SECRET",
  "GITHUB_OAUTH_CLIENT_ID",
  "GITHUB_OAUTH_CLIENT_SECRET",
  "CODEMATE_RBAC_ADMIN_USERS",
  "CODEMATE_RBAC_ADMIN_TEAMS",
  "CODEMATE_RBAC_VIEWER_USERS",
  "CODEMATE_RBAC_VIEWER_TEAMS",
  "CODEMATE_RBAC_VIEWER_ORGS"
] as const;

const originalEnv = new Map(AUTH_ENV_KEYS.map((key) => [key, process.env[key]]));

describe("admin session signing", () => {
  afterEach(() => {
    for (const key of AUTH_ENV_KEYS) {
      const original = originalEnv.get(key);
      if (original === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = original;
      }
    }
  });

  it("uses the product API token instead of the public local-development fallback", () => {
    clearAuthEnvironment();
    process.env.CODEMATE_PRODUCT_API_TOKEN = "product-token-with-at-least-32-characters";
    process.env.GITHUB_OAUTH_CLIENT_ID = "client-id";
    process.env.GITHUB_OAUTH_CLIENT_SECRET = "client-secret";
    process.env.CODEMATE_RBAC_ADMIN_USERS = "victim";

    const now = Date.now();
    const legitimate = createAdminSessionValue("admin", githubUser("victim"), now);
    const forged = forgeSessionWithKnownLocalSecret("victim", now);

    expect(parseAdminSession(legitimate, now)).toMatchObject({ role: "admin" });
    expect(parseAdminSession(forged, now)).toBeNull();
  });

  it("fails closed when protected GitHub authentication has no session signing secret", () => {
    clearAuthEnvironment();
    process.env.GITHUB_OAUTH_CLIENT_ID = "client-id";
    process.env.GITHUB_OAUTH_CLIENT_SECRET = "client-secret";
    process.env.CODEMATE_RBAC_ADMIN_USERS = "alice";

    expect(adminSessionState(undefined)).toMatchObject({
      authenticated: false,
      misconfigured: true,
      detail: "Configure FRONTEND_ADMIN_SESSION_SECRET before enabling protected authentication."
    });
  });
});

function clearAuthEnvironment() {
  for (const key of AUTH_ENV_KEYS) {
    delete process.env[key];
  }
}

function githubUser(login: string) {
  return {
    provider: "github" as const,
    login,
    name: login,
    avatarUrl: null
  };
}

function forgeSessionWithKnownLocalSecret(login: string, now: number): string {
  const payload = Buffer.from(
    JSON.stringify({
      version: 2,
      expiresAt: now + 60_000,
      role: "admin",
      user: githubUser(login)
    })
  ).toString("base64url");
  const signature = createHmac("sha256", "codemate-local-dev")
    .update(payload)
    .digest("base64url");
  return `${payload}.${signature}`;
}
