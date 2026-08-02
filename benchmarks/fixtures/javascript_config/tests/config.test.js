import assert from "node:assert/strict";
import test from "node:test";

import { readRequestTimeout } from "../src/config.js";

test("negative request timeout falls back to the safe default", () => {
  assert.equal(readRequestTimeout({ REQUEST_TIMEOUT_MS: "-1" }), 5000);
});
