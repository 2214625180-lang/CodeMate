import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentTimeline } from "@/components/agent/AgentTimeline";
import { TestResultPanel } from "@/components/agent/TestResultPanel";
import { DiffViewer } from "@/components/diff/DiffViewer";

afterEach(cleanup);

describe("agent repair presentation", () => {
  it("renders evidence, a patch, and the strict verification verdict", () => {
    render(
      <>
        <AgentTimeline
          events={[
            {
              id: "plan-1",
              run_id: "run-1",
              type: "agent_plan",
              tool_name: null,
              input: null,
              output: { action: { action: "SearchCode" } },
              duration_ms: null,
              created_at: "2026-08-03T00:00:00+00:00"
            },
            {
              id: "patch-1",
              run_id: "run-1",
              type: "patch",
              tool_name: null,
              input: null,
              output: { diff: "--- a/src/cart.js\n+++ b/src/cart.js\n-return total\n+return total - discount" },
              duration_ms: null,
              created_at: "2026-08-03T00:00:01+00:00"
            },
            {
              id: "verification-1",
              run_id: "run-1",
              type: "verification",
              tool_name: null,
              input: null,
              output: { status: "verified_success", reason: "all_suites_passed" },
              duration_ms: null,
              created_at: "2026-08-03T00:00:02+00:00"
            }
          ]}
        />
        <TestResultPanel
          result={{
            status: "verified_success",
            reason: "baseline_failed_and_post_patch_suites_passed",
            baseline: { command: "npm test", exit_code: 1, tests_ran: true, passed: false },
            targeted: { command: "npm test -- cart", exit_code: 0, tests_ran: true, passed: true },
            regression: { command: "npm test", exit_code: 0, tests_ran: true, passed: true }
          }}
        />
        <DiffViewer diff="--- a/src/cart.js\n+++ b/src/cart.js\n-return total\n+return total - discount" />
      </>
    );

    expect(screen.getByText("Plan Next Action · SearchCode")).toBeInTheDocument();
    expect(screen.getByText("Patch")).toBeInTheDocument();
    expect(screen.getByText("Verification Verdict")).toBeInTheDocument();
    expect(screen.getAllByText("verified_success").length).toBeGreaterThan(0);
    expect(screen.getByText("Baseline reproduction")).toBeInTheDocument();
    expect(screen.getByText("Targeted tests")).toBeInTheDocument();
    expect(screen.getByText("Regression checks")).toBeInTheDocument();
    expect(screen.getAllByText("+return total - discount").length).toBeGreaterThan(0);
  });

  it("does not render a success verdict when tests were skipped", () => {
    render(
      <TestResultPanel
        result={{
          phase: "targeted",
          tests_ran: false,
          skipped_reason: "dependencies unavailable",
          passed: true,
          exit_code: 0
        }}
      />
    );

    expect(screen.getByText("skipped")).toBeInTheDocument();
    expect(screen.queryByText("passed")).not.toBeInTheDocument();
  });
});
