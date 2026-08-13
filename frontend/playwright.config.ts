import { defineConfig, devices } from "@playwright/test";

const frontendPort = 3100;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const backendUrl = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:18000";

export default defineConfig({
  testDir: "./e2e",
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
      BACKEND_API_BASE_URL: backendUrl
    },
    reuseExistingServer: false,
    timeout: 120_000
  }
});
