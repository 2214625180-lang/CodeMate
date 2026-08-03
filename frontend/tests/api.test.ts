import { afterEach, describe, expect, it, vi } from "vitest";

import { createFixRun, getFileContent, reviewRepository } from "@/lib/api";

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
      "http://localhost:8000/repos/repo-1/fix",
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
