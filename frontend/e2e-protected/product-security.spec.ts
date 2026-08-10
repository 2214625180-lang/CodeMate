import { createHmac, randomUUID } from "node:crypto";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

import {
  ADMIN_SESSION_COOKIE,
  createAdminSessionValue
} from "../lib/adminSession";

const frontendBaseUrl = "http://127.0.0.1:3100";
const backendBaseUrl = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:18000";
const frontendOrigin = new URL(frontendBaseUrl).origin;
const backendOrigin = new URL(backendBaseUrl).origin;
const aliceRepositoryId = "e2e-alice-repo";
const aliceRunId = "e2e-alice-run";
const bobRepositoryId = "e2e-bob-repo";
const bobRunId = "e2e-bob-run";

test.describe.configure({ mode: "serial" });

test("keeps Alice and Bob isolated while product traffic uses the signed proxy", async ({
  browser
}) => {
  assertProtectedEnvironment();
  const aliceContext = await authenticatedContext(browser, "alice");
  const bobContext = await authenticatedContext(browser, "bob");

  try {
    const alicePage = await aliceContext.newPage();
    const browserRequests = trackBrowserRequests(alicePage);

    await alicePage.goto("/repos");
    await expect(
      alicePage.getByRole("link", { name: "alice-protected-cart" })
    ).toBeVisible();
    await expect(
      alicePage.getByRole("link", { name: "bob-protected-inventory" })
    ).toHaveCount(0);

    const aliceRepositories = await aliceContext.request.get(
      `${frontendBaseUrl}/api/backend/repos`
    );
    expect(aliceRepositories.status()).toBe(200);
    expect((await aliceRepositories.json()).map((repo: { id: string }) => repo.id)).toEqual([
      aliceRepositoryId
    ]);

    const bobRepositories = await bobContext.request.get(
      `${frontendBaseUrl}/api/backend/repos`
    );
    expect(bobRepositories.status()).toBe(200);
    expect((await bobRepositories.json()).map((repo: { id: string }) => repo.id)).toEqual([
      bobRepositoryId
    ]);

    await expectNotFound(
      aliceContext,
      `/api/backend/repos/${bobRepositoryId}`
    );
    await expectNotFound(aliceContext, `/api/backend/runs/${bobRunId}`);

    const chatResponsePromise = alicePage.waitForResponse((response) =>
      response.url().endsWith(`/api/backend/repos/${aliceRepositoryId}/chat`)
    );
    await alicePage.goto(`/repos/${aliceRepositoryId}/chat`);
    await alicePage.getByLabel("Question").fill("Where is calculateTotal implemented?");
    await alicePage.getByRole("button", { name: "Ask" }).click();
    expect((await chatResponsePromise).status()).toBe(200);
    await expect(alicePage.getByText(/根据当前索引/)).toBeVisible();
    await expect(alicePage.getByText(/src\/checkout\.js/).first()).toBeVisible();

    const runResponsePromise = alicePage.waitForResponse((response) =>
      response.url().endsWith(`/api/backend/runs/${aliceRunId}`)
    );
    const traceResponsePromise = alicePage.waitForResponse((response) =>
      response.url().endsWith(`/api/backend/runs/${aliceRunId}/trace`)
    );
    await alicePage.goto(`/repos/${aliceRepositoryId}/fix?runId=${aliceRunId}`);
    expect((await runResponsePromise).status()).toBe(200);
    expect((await traceResponsePromise).status()).toBe(200);
    await expect(alicePage.getByText("Verification Verdict")).toBeVisible();
    await expect(alicePage.getByText("verified_success").last()).toBeVisible();

    const fixResponse = await aliceContext.request.post(
      `${frontendBaseUrl}/api/backend/repos/${aliceRepositoryId}/fix`,
      {
        data: {
          issue: "Create a protected-mode ownership run.",
          test_command: "npm test"
        }
      }
    );
    expect(fixResponse.status()).toBe(202);
    const createdRun = (await fixResponse.json()) as { run_id: string; status: string };
    expect(createdRun.status).toBe("pending");
    expect(
      (
        await aliceContext.request.get(
          `${frontendBaseUrl}/api/backend/runs/${createdRun.run_id}`
        )
      ).status()
    ).toBe(200);
    await expectNotFound(bobContext, `/api/backend/runs/${createdRun.run_id}`);

    const proxyPaths = browserRequests
      .filter((url) => new URL(url).origin === frontendOrigin)
      .map((url) => new URL(url).pathname);
    expect(proxyPaths).toEqual(
      expect.arrayContaining([
        "/api/backend/repos",
        `/api/backend/repos/${aliceRepositoryId}/chat`,
        `/api/backend/runs/${aliceRunId}`,
        `/api/backend/runs/${aliceRunId}/trace`
      ])
    );
    expect(
      browserRequests.filter((url) => new URL(url).origin === backendOrigin)
    ).toEqual([]);
  } finally {
    await aliceContext.close();
    await bobContext.close();
  }
});

test("rejects replay of a signed product identity nonce in Redis", async ({ request }) => {
  assertProtectedEnvironment();
  const path = "/repos";
  const unsignedResponse = await request.get(`${backendBaseUrl}${path}`, {
    headers: {
      Authorization: `Bearer ${requiredEnvironment("CODEMATE_PRODUCT_API_TOKEN")}`
    }
  });
  expect(unsignedResponse.status()).toBe(401);
  expect(await unsignedResponse.json()).toEqual({
    detail: "Valid signed product identity required"
  });

  const headers = signedProductHeaders("GET", path, "alice");

  const firstResponse = await request.get(`${backendBaseUrl}${path}`, { headers });
  expect(firstResponse.status()).toBe(200);

  const replayedResponse = await request.get(`${backendBaseUrl}${path}`, { headers });
  expect(replayedResponse.status()).toBe(401);
  expect(await replayedResponse.json()).toEqual({
    detail: "Product identity nonce already used"
  });
});

async function authenticatedContext(
  browser: Browser,
  login: "alice" | "bob"
): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addCookies([
    {
      name: ADMIN_SESSION_COOKIE,
      value: createAdminSessionValue("admin", {
        provider: "github",
        login,
        name: login === "alice" ? "Alice" : "Bob",
        avatarUrl: null
      }),
      url: frontendBaseUrl,
      httpOnly: true,
      sameSite: "Lax"
    }
  ]);
  return context;
}

async function expectNotFound(context: BrowserContext, path: string): Promise<void> {
  const response = await context.request.get(`${frontendBaseUrl}${path}`);
  expect(response.status()).toBe(404);
}

function trackBrowserRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  return requests;
}

function signedProductHeaders(method: string, path: string, login: string): Record<string, string> {
  const productToken = requiredEnvironment("CODEMATE_PRODUCT_API_TOKEN");
  const identitySecret = requiredEnvironment("CODEMATE_PRODUCT_IDENTITY_SECRET");
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const provider = "github";
  const payload = [
    "v1",
    timestamp,
    nonce,
    method.toUpperCase(),
    path,
    login,
    provider
  ].join("\n");

  return {
    Authorization: `Bearer ${productToken}`,
    "X-CodeMate-Product-User": login,
    "X-CodeMate-Product-Provider": provider,
    "X-CodeMate-Product-Identity-Timestamp": timestamp,
    "X-CodeMate-Product-Identity-Nonce": nonce,
    "X-CodeMate-Product-Identity-Signature": createHmac("sha256", identitySecret)
      .update(payload)
      .digest("base64url")
  };
}

function assertProtectedEnvironment(): void {
  requiredEnvironment("CODEMATE_PRODUCT_API_TOKEN");
  requiredEnvironment("CODEMATE_PRODUCT_IDENTITY_SECRET");
  requiredEnvironment("FRONTEND_ADMIN_SESSION_SECRET");
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for the protected E2E suite`);
  }
  return value;
}
