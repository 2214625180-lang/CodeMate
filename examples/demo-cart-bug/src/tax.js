export function calculateTax(taxableAmount, taxRate) {
  if (!Number.isFinite(taxableAmount) || taxableAmount < 0) {
    throw new TypeError("taxableAmount must be a non-negative number");
  }
  if (!Number.isFinite(taxRate) || taxRate < 0 || taxRate > 1) {
    throw new TypeError("taxRate must be between 0 and 1");
  }

  return Math.round(taxableAmount * taxRate * 100) / 100;
}
