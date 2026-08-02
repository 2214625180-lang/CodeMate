import assert from "node:assert/strict";
import test from "node:test";

import { withRetry } from "../src/retry.js";

test("maxRetries two executes one initial attempt and two retries", async () => {
  let attempts = 0;
  await assert.rejects(
    withRetry(async () => {
      attempts += 1;
      throw new Error("payment unavailable");
    }, 2),
    /payment unavailable/
  );

  assert.equal(attempts, 3);
});
