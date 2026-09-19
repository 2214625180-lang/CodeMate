import { defineConfig, devices } from "@playwright/test";

const frontendPort = 3100;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const backendUrl = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:18000";
const testDir = process.env.CODEMATE_E2E_SUITE === "protected"
  ? "./e2e-protected"
  : "./e2e";

export default defineConfig({
  testDir,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
    screenshot: "only-on-failure"
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run dev -- --hostname 127.0.0.1 --port ${frontendPort}`,
    url: frontendUrl,
    env: {
      NEXT_PUBLIC_API_BASE_URL: backendUrl,
      BACKEND_API_BASE_URL: backendUrl,
      CODEMATE_PRODUCT_API_TOKEN: process.env.CODEMATE_PRODUCT_API_TOKEN ?? "",
      CODEMATE_PRODUCT_IDENTITY_SECRET:
        process.env.CODEMATE_PRODUCT_IDENTITY_SECRET ?? "",
      FRONTEND_ADMIN_SESSION_SECRET: process.env.FRONTEND_ADMIN_SESSION_SECRET ?? "",
      GITHUB_OAUTH_CLIENT_ID: process.env.GITHUB_OAUTH_CLIENT_ID ?? "",
      GITHUB_OAUTH_CLIENT_SECRET: process.env.GITHUB_OAUTH_CLIENT_SECRET ?? "",
      CODEMATE_RBAC_ADMIN_USERS: process.env.CODEMATE_RBAC_ADMIN_USERS ?? ""
    },
    reuseExistingServer: false,
    timeout: 120_000
  }
});
