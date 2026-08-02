import { applyFixedCoupon, calculateSubtotal } from "./cart.js";
import { calculateTax } from "./tax.js";

export function quoteCheckout({ lines, couponAmount = 0, taxRate }) {
  const subtotal = calculateSubtotal(lines);
  const discountedSubtotal = applyFixedCoupon(subtotal, couponAmount);
  const tax = calculateTax(subtotal, taxRate);

  return {
    subtotal,
    discountedSubtotal,
    tax,
    total: discountedSubtotal + tax
  };
}
