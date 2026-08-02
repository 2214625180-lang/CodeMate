import assert from "node:assert/strict";
import test from "node:test";

import { applyFixedCoupon } from "../src/cart.js";

test("a fixed coupon never makes the discounted subtotal negative", () => {
  assert.equal(applyFixedCoupon(30, 50), 0);
});
