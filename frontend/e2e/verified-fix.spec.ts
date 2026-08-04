import { expect, test } from "@playwright/test";

const backendBaseUrl = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:18000";
const repoId = "e2e-demo-cart";
const runId = "e2e-run-demo-cart";

test("streams a verified fix from the Compose backend and persists feedback", async ({
  page,
  request
}) => {
  const readiness = await request.get(`${backendBaseUrl}/health/readiness`);
  expect(readiness.ok()).toBeTruthy();

  await page.goto("/repos");
  await expect(page.getByRole("link", { name: "e2e-demo-cart-bug" })).toBeVisible();

  await page.goto(`/repos/${repoId}/fix?runId=${runId}`);

  await expect(page.getByRole("heading", { name: /^Plan Next Action/ })).toBeVisible();
  await expect(page.getByText("Verification Verdict")).toBeVisible();
  await expect(page.getByText("verified_success").last()).toBeVisible();
  await expect(
    page.getByText("+  const tax = calculateTax(discountedSubtotal, taxRate);").first()
  ).toBeVisible();
  await expect(page.getByText("Baseline reproduction").first()).toBeVisible();
  await expect(page.getByText("Targeted tests").first()).toBeVisible();
  await expect(page.getByText("Regression checks").first()).toBeVisible();
  await page.getByRole("button", { name: "accepted" }).click();
  await expect(page.getByText("Feedback: accepted")).toBeVisible();
});
