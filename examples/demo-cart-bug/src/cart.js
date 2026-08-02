function requireNonNegativeMoney(value, fieldName) {
  if (!Number.isFinite(value) || value < 0) {
    throw new TypeError(`${fieldName} must be a non-negative number`);
  }
}

export function calculateSubtotal(lines) {
  if (!Array.isArray(lines) || lines.length === 0) {
    throw new TypeError("lines must contain at least one cart item");
  }

  return lines.reduce((subtotal, line) => {
    requireNonNegativeMoney(line.unitPrice, "line.unitPrice");
    if (!Number.isInteger(line.quantity) || line.quantity <= 0) {
      throw new TypeError("line.quantity must be a positive integer");
    }
    return subtotal + line.unitPrice * line.quantity;
  }, 0);
}

export function applyFixedCoupon(subtotal, couponAmount) {
  requireNonNegativeMoney(subtotal, "subtotal");
  requireNonNegativeMoney(couponAmount, "couponAmount");
  return subtotal - couponAmount;
}
