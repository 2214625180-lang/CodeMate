import assert from "node:assert/strict";
import test from "node:test";

import { quoteCheckout } from "../src/checkout.js";

test("checkout calculates tax from the discounted subtotal", () => {
  assert.deepEqual(
    quoteCheckout({
      lines: [{ unitPrice: 50, quantity: 2 }],
      couponAmount: 20,
      taxRate: 0.1
    }),
    {
      subtotal: 100,
      discountedSubtotal: 80,
      tax: 8,
      total: 88
    }
  );
});

test("a coupon larger than the subtotal produces a zero checkout total", () => {
  assert.deepEqual(
    quoteCheckout({
      lines: [{ unitPrice: 15, quantity: 2 }],
      couponAmount: 50,
      taxRate: 0.1
    }),
    {
      subtotal: 30,
      discountedSubtotal: 0,
      tax: 0,
      total: 0
    }
  );
});
