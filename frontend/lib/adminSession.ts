import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const ADMIN_SESSION_COOKIE = "codemate_eval_admin";
export const GITHUB_OAUTH_STATE_COOKIE = "codemate_github_oauth_state";

const SESSION_TTL_MS = 8 * 60 * 60 * 1000;
const OAUTH_STATE_TTL_SECONDS = 10 * 60;

export type AdminRole = "admin" | "viewer";
export type AuthMode = "open" | "github" | "password" | "misconfigured";

export type AdminUser = {
  provider: "github" | "password" | "local";
  login: string;
  name: string | null;
  avatarUrl: string | null;
};

export type AdminSession = {
  version: 2;
  expiresAt: number;
  role: AdminRole;
  user: AdminUser;
};

export type AdminSessionState = {
  authRequired: boolean;
  authenticated: boolean;
  misconfigured: boolean;
  authMode: AuthMode;
  role: AdminRole | null;
  user: AdminUser | null;
  detail?: string;
};

export type GitHubOAuthConfig = {
  clientId: string;
  clientSecret: string;
  redirectUri: string | null;
};

export type GitHubIdentity = {
  login: string;
  name: string | null;
  avatarUrl: string | null;
  orgs: string[];
  teams: string[];
};

export type RbacConfig = {
  adminUsers: Set<string>;
  adminTeams: Set<string>;
  viewerUsers: Set<string>;
  viewerTeams: Set<string>;
  viewerOrgs: Set<string>;
};

export function backendEvaluationApiToken(): string {
  return (
    process.env.CODEMATE_EVALUATION_API_TOKEN ||
    process.env.EVALUATION_ADMIN_TOKEN ||
    ""
  ).trim();
}

export function backendProductApiToken(): string {
  return (
    process.env.CODEMATE_PRODUCT_API_TOKEN ||
    process.env.PRODUCT_API_TOKEN ||
    ""
  ).trim();
}

export function frontendAdminPassword(): string {
  return (
    process.env.FRONTEND_ADMIN_PASSWORD ||
    process.env.CODEMATE_FRONTEND_ADMIN_PASSWORD ||
    ""
  ).trim();
}

export function githubOAuthConfig(): GitHubOAuthConfig | null {
  const clientId = (process.env.GITHUB_OAUTH_CLIENT_ID || "").trim();
  const clientSecret = (process.env.GITHUB_OAUTH_CLIENT_SECRET || "").trim();
  if (!clientId || !clientSecret) {
    return null;
  }
  return {
    clientId,
    clientSecret,
    redirectUri: (process.env.GITHUB_OAUTH_REDIRECT_URI || "").trim() || null
  };
}

export function rbacConfig(): RbacConfig {
  return {
    adminUsers: parseCsvSet(process.env.CODEMATE_RBAC_ADMIN_USERS),
    adminTeams: parseCsvSet(process.env.CODEMATE_RBAC_ADMIN_TEAMS),
    viewerUsers: parseCsvSet(process.env.CODEMATE_RBAC_VIEWER_USERS),
    viewerTeams: parseCsvSet(process.env.CODEMATE_RBAC_VIEWER_TEAMS),
    viewerOrgs: parseCsvSet(process.env.CODEMATE_RBAC_VIEWER_ORGS)
  };
}

export function adminSessionState(cookieValue: string | undefined): AdminSessionState {
  const hasBackendToken = Boolean(backendEvaluationApiToken() || backendProductApiToken());
  const hasPassword = Boolean(frontendAdminPassword());
  const hasGitHub = Boolean(githubOAuthConfig());
  const authRequired = hasBackendToken || hasPassword || hasGitHub;
  const hasSessionSecret = Boolean(configuredSessionSecret());
  const rbac = rbacConfig();
  const hasRbacRules = hasAnyRbacRule(rbac);
  const misconfigured = hasBackendToken && !hasPassword && !hasGitHub
    ? true
    : hasGitHub && !hasRbacRules
      ? true
      : authRequired && !hasSessionSecret;

  if (!authRequired) {
    return {
      authRequired: false,
      authenticated: true,
      misconfigured: false,
      authMode: "open",
      role: "admin",
      user: {
        provider: "local",
        login: "local-dev",
        name: "Local Development",
        avatarUrl: null
      }
    };
  }

  if (misconfigured) {
    return {
      authRequired: true,
      authenticated: false,
      misconfigured: true,
      authMode: "misconfigured",
      role: null,
      user: null,
      detail: misconfigurationDetail(
        hasBackendToken,
        hasPassword,
        hasGitHub,
        hasRbacRules,
        hasSessionSecret
      )
    };
  }

  const session = parseAdminSession(cookieValue);
  return {
    authRequired,
    authenticated: Boolean(session),
    misconfigured: false,
    authMode: hasGitHub ? "github" : "password",
    role: session?.role ?? null,
    user: session?.user ?? null
  };
}

export function canAccessEvaluationProxy(state: AdminSessionState): boolean {
  return !state.misconfigured && (!state.authRequired || state.authenticated);
}

export function canMutateEvaluation(state: AdminSessionState): boolean {
  return canAccessEvaluationProxy(state) && state.role === "admin";
}

export function resolveGitHubRole(identity: GitHubIdentity): AdminRole | null {
  const config = rbacConfig();
  const login = normalize(identity.login);
  const teams = new Set(identity.teams.map(normalize));
  const orgs = new Set(identity.orgs.map(normalize));

  if (config.adminUsers.has(login) || intersects(config.adminTeams, teams)) {
    return "admin";
  }
  if (
    config.viewerUsers.has(login) ||
    intersects(config.viewerTeams, teams) ||
    intersects(config.viewerOrgs, orgs)
  ) {
    return "viewer";
  }
  return null;
}

export function verifyFrontendAdminPassword(password: string): boolean {
  const expected = frontendAdminPassword();
  if (!expected) {
    return false;
  }
  return safeEqual(password, expected);
}

export function createAdminSessionValue(
  role: AdminRole = "admin",
  user: AdminUser = {
    provider: "password",
    login: "password-admin",
    name: "Password Admin",
    avatarUrl: null
  },
  now = Date.now()
): string {
  const session: AdminSession = {
    version: 2,
    expiresAt: now + SESSION_TTL_MS,
    role,
    user
  };
  const payload = Buffer.from(JSON.stringify(session)).toString("base64url");
  return `${payload}.${sign(payload)}`;
}

export function parseAdminSession(value: string | undefined, now = Date.now()): AdminSession | null {
  if (!value) {
    return null;
  }

  const legacy = parseLegacySession(value, now);
  if (legacy) {
    return legacy;
  }

  const [payload, signature, extra] = value.split(".");
  if (!payload || !signature || extra) {
    return null;
  }
  if (!safeEqual(signature, sign(payload))) {
    return null;
  }

  try {
    const parsed = JSON.parse(Buffer.from(payload, "base64url").toString("utf-8")) as AdminSession;
    if (parsed.version !== 2 || parsed.expiresAt <= now || !isRole(parsed.role)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function adminCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: Math.floor(SESSION_TTL_MS / 1000)
  };
}

export function oauthStateCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: OAUTH_STATE_TTL_SECONDS
  };
}

export function createOAuthState(): string {
  return cryptoRandom();
}

function parseLegacySession(value: string, now: number): AdminSession | null {
  const parts = value.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") {
    return null;
  }

  const expiresAt = Number(parts[1]);
  if (!Number.isFinite(expiresAt) || expiresAt <= now) {
    return null;
  }
  if (!safeEqual(parts[2], sign(`${parts[0]}.${parts[1]}`))) {
    return null;
  }
  return {
    version: 2,
    expiresAt,
    role: "admin",
    user: {
      provider: "password",
      login: "password-admin",
      name: "Password Admin",
      avatarUrl: null
    }
  };
}

function sign(payload: string): string {
  return createHmac("sha256", sessionSecret()).update(payload).digest("base64url");
}

function sessionSecret(): string {
  const configured = configuredSessionSecret();
  if (configured) {
    return configured;
  }
  if (
    !frontendAdminPassword() &&
    !backendEvaluationApiToken() &&
    !backendProductApiToken() &&
    !githubOAuthConfig()
  ) {
    return "codemate-local-dev";
  }
  throw new Error("FRONTEND_ADMIN_SESSION_SECRET is required for protected authentication");
}

function configuredSessionSecret(): string {
  return (
    process.env.FRONTEND_ADMIN_SESSION_SECRET ||
    process.env.CODEMATE_FRONTEND_SESSION_SECRET ||
    frontendAdminPassword() ||
    backendEvaluationApiToken() ||
    backendProductApiToken()
  ).trim();
}

function parseCsvSet(value: string | undefined): Set<string> {
  return new Set(
    (value || "")
      .split(",")
      .map((item) => normalize(item))
      .filter(Boolean)
  );
}

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

function hasAnyRbacRule(config: RbacConfig): boolean {
  return (
    config.adminUsers.size > 0 ||
    config.adminTeams.size > 0 ||
    config.viewerUsers.size > 0 ||
    config.viewerTeams.size > 0 ||
    config.viewerOrgs.size > 0
  );
}

function intersects(left: Set<string>, right: Set<string>): boolean {
  for (const item of left) {
    if (right.has(item)) {
      return true;
    }
  }
  return false;
}

function misconfigurationDetail(
  hasBackendToken: boolean,
  hasPassword: boolean,
  hasGitHub: boolean,
  hasRbacRules: boolean,
  hasSessionSecret: boolean
): string {
  if (hasBackendToken && !hasPassword && !hasGitHub) {
    return "Configure GitHub OAuth or FRONTEND_ADMIN_PASSWORD when a CodeMate API token is set.";
  }
  if (hasGitHub && !hasRbacRules) {
    return "Configure at least one CODEMATE_RBAC_* rule before enabling GitHub OAuth.";
  }
  if (!hasSessionSecret) {
    return "Configure FRONTEND_ADMIN_SESSION_SECRET before enabling protected authentication.";
  }
  return "Evaluation authentication is not configured correctly.";
}

function isRole(value: unknown): value is AdminRole {
  return value === "admin" || value === "viewer";
}

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }
  return timingSafeEqual(leftBuffer, rightBuffer);
}

function cryptoRandom(): string {
  return randomBytes(32).toString("hex");
}
