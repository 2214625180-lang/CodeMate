import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RepoFixPage from "@/app/repos/[repoId]/fix/page";
import type { AgentRun } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  createFixRun: vi.fn(),
  decideMCPApproval: vi.fn(),
  getRun: vi.fn(),
  reconcileMCPExecution: vi.fn(),
  replace: vi.fn(),
  requestedRunId: "old-run",
  submitRunFeedback: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ repoId: "repo-1" }),
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => ({
    get: (name: string) => (name === "runId" ? mocks.requestedRunId : null)
  })
}));

vi.mock("@/lib/api", () => ({
  backendApiUrl: (path: string) => `/api/backend${path}`,
  createFixRun: mocks.createFixRun,
  decideMCPApproval: mocks.decideMCPApproval,
  getRun: mocks.getRun,
  reconcileMCPExecution: mocks.reconcileMCPExecution,
  submitRunFeedback: mocks.submitRunFeedback
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  addEventListener() {}

  close() {}
}

describe("fix page active run lifecycle", () => {
  beforeEach(() => {
    mocks.requestedRunId = "old-run";
    mocks.createFixRun.mockResolvedValue({ run_id: "new-run", status: "pending" });
    mocks.getRun.mockImplementation(async (runId: string) => agentRun(runId, "failed"));
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps a newly started run active instead of restoring the URL's old run", async () => {
    const user = userEvent.setup();
    render(<RepoFixPage />);

    await waitFor(() => expect(mocks.getRun).toHaveBeenCalledWith("old-run"));
    await user.click(await screen.findByRole("button", { name: "Start fix" }));

    await waitFor(() => {
      expect(mocks.replace).toHaveBeenCalledWith("/repos/repo-1/fix?runId=new-run", {
        scroll: false
      });
    });
    expect(FakeEventSource.instances.map((source) => source.url)).toEqual([
      "/api/backend/runs/old-run/trace",
      "/api/backend/runs/new-run/trace"
    ]);
  });

  it("does not unlock duplicate submission when a running trace disconnects", async () => {
    mocks.getRun.mockResolvedValue(agentRun("old-run", "running"));
    render(<RepoFixPage />);

    const startButton = await screen.findByRole("button", { name: "Running..." });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].onerror?.(new Event("error"));
    });

    await waitFor(() => expect(mocks.getRun).toHaveBeenCalledTimes(2));
    expect(startButton).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Start fix" })).not.toBeInTheDocument();
  });
});

function agentRun(id: string, status: AgentRun["status"]): AgentRun {
  return {
    id,
    repo_id: "repo-1",
    task_type: "fix",
    tenant_id: null,
    principal_type: "user",
    principal_id: "local:local-dev",
    delegated_identity_id: null,
    user_input: "fix the cart",
    test_command: "npm test",
    status,
    final_diff: null,
    final_summary: null,
    failure_reason: null,
    test_result: null,
    iterations: 0,
    feedback_status: null,
    feedback_note: null,
    feedback_at: null,
    created_at: "2026-08-09T00:00:00Z",
    updated_at: "2026-08-09T00:00:00Z",
    finished_at: status === "running" ? null : "2026-08-09T00:00:01Z",
    steps: []
  };
}
