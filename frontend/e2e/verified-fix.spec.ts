import { expect, test } from "@playwright/test";

const now = "2026-08-03T00:00:00+00:00";

const seededRepository = {
  id: "demo-cart",
  name: "demo-cart-bug",
  tenant_id: null,
  repo_url: "https://example.test/demo-cart-bug.git",
  local_path: "/fixtures/demo-cart-bug",
  status: "indexed",
  error_message: null,
  language_summary: { javascript: 3 },
  last_commit_hash: "fixture-commit",
  file_count: 3,
  chunk_count: 6,
  indexed_at: now,
  created_at: now,
  updated_at: now
};

const verifiedRun = {
  id: "run-demo-cart",
  repo_id: "demo-cart",
  task_type: "fix",
  tenant_id: null,
  principal_type: "agent",
  principal_id: "codemate-agent",
  delegated_identity_id: null,
  user_input: "Coupon is deducted after tax, so checkout total is too high.",
  test_command: "npm test",
  status: "verified_success",
  final_diff:
    "--- a/src/checkout.js\n+++ b/src/checkout.js\n@@\n-return subtotal + tax - coupon.discount\n+return subtotal - coupon.discount + tax\n",
  final_summary: "Patch 前已复现失败；Patch 后目标测试与回归测试均实际执行并通过。",
  failure_reason: null,
  test_result: {
    status: "verified_success",
    baseline: { command: "npm test", tests_ran: true, exit_code: 1, passed: false },
    targeted: { command: "npm test -- cart-coupon", tests_ran: true, exit_code: 0, passed: true },
    regression: { command: "npm test", tests_ran: true, exit_code: 0, passed: true }
  },
  iterations: 2,
  feedback_status: null,
  feedback_note: null,
  feedback_at: null,
  created_at: now,
  updated_at: now,
  finished_at: now,
  steps: []
};

test("seed repository → start fix → timeline → diff → verified tests", async ({ page }) => {
  let repositories: typeof seededRepository[] = [];
  await page.route("http://localhost:8000/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/repos" && request.method() === "GET") {
      await route.fulfill({ json: repositories });
      return;
    }
    if (pathname === "/repos" && request.method() === "POST") {
      repositories = [seededRepository];
      await route.fulfill({ status: 201, json: seededRepository });
      return;
    }
    if (pathname === "/repos/demo-cart/fix" && request.method() === "POST") {
      await route.fulfill({ status: 202, json: { run_id: verifiedRun.id, status: "pending" } });
      return;
    }
    if (pathname === `/runs/${verifiedRun.id}/trace`) {
      const events = [
        ["agent_plan", { action: { action: "SearchCode" } }],
        ["patch", { diff: verifiedRun.final_diff }],
        ["verification", verifiedRun.test_result],
        ["final", { status: "verified_success" }]
      ]
        .map(
          ([type, output], index) =>
            `event: ${type}\ndata: ${JSON.stringify({ id: `event-${index}`, run_id: verifiedRun.id, type, output, created_at: now })}\n\n`
        )
        .join("");
      await route.fulfill({
        contentType: "text/event-stream",
        body: events
      });
      return;
    }
    if (pathname === `/runs/${verifiedRun.id}`) {
      await route.fulfill({ json: verifiedRun });
      return;
    }
    await route.fulfill({ status: 404, body: "unexpected test request" });
  });

  await page.goto("/repos");
  await page.getByLabel("Git repository URL").fill(seededRepository.repo_url);
  await page.getByRole("button", { name: "Add repository" }).click();
  await expect(page.getByRole("link", { name: "demo-cart-bug" })).toBeVisible();

  await page.goto(`/repos/${seededRepository.id}/fix`);
  await page
    .getByLabel("Error log or failing test")
    .fill("Coupon is deducted after tax, so checkout total is too high.");
  await page.getByRole("button", { name: "Start fix" }).click();

  await expect(page.getByText("Plan Next Action · SearchCode")).toBeVisible();
  await expect(page.getByText("Verification Verdict")).toBeVisible();
  await expect(page.getByText("verified_success").last()).toBeVisible();
  await expect(page.getByText("+return subtotal - coupon.discount + tax").first()).toBeVisible();
  await expect(page.getByText("Baseline reproduction").first()).toBeVisible();
  await expect(page.getByText("Targeted tests").first()).toBeVisible();
  await expect(page.getByText("Regression checks").first()).toBeVisible();
});
