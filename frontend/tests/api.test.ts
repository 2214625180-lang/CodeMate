import { afterEach, describe, expect, it, vi } from "vitest";

import {
  backendApiUrl,
  createFixRun,
  getFileContent,
  listRepositories,
  reviewRepository
} from "@/lib/api";

describe("frontend API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes a fix request and omits incomplete delegated credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: "run-1", status: "pending" }), { status: 202 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(createFixRun("repo-1", "cart total is wrong", "npm test", { identityId: "id", delegationToken: "" })).resolves.toEqual({
      run_id: "run-1",
      status: "pending"
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/repos/repo-1/fix",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          issue: "cart total is wrong",
          test_command: "npm test",
          delegated_identity_id: null,
          delegation_token: null
        })
      })
    );
  });

  it("routes product APIs through the signed server-side proxy", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listRepositories()).resolves.toEqual([]);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/repos",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(backendApiUrl("/runs/run-1/trace")).toBe("/api/backend/runs/run-1/trace");
    expect(() => backendApiUrl("repos")).toThrow("must start with '/'");
  });

  it("encodes file paths and surfaces backend failures", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ file_path: "src/cart.ts", content: "ok" }), { status: 200 })
      )
      .mockResolvedValueOnce(new Response("review unavailable", { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getFileContent("repo-1", "src/cart.ts", 2, 4)).resolves.toMatchObject({
      content: "ok"
    });
    await expect(reviewRepository("repo-1", { diff: "diff" })).rejects.toThrow("review unavailable");
    expect(fetchMock.mock.calls[0][0]).toContain("path=src%2Fcart.ts");
  });
});
