import assert from "node:assert/strict";
import test from "node:test";

import { buildUserLabel } from "../src/composables/useUserLabel.js";

test("user labels trim transport whitespace", () => {
  assert.equal(buildUserLabel({ name: "  Ada  " }), "Signed in as Ada");
});
