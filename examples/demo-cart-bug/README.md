# Demo Cart Bug

This dependency-free fixture is intentionally broken in two related places:

- the targeted coupon test exposes a negative discounted subtotal in `src/cart.js`;
- the full regression suite also checks that `src/checkout.js` calculates tax from the discounted subtotal.

The split is deliberate. A narrow first patch can pass the targeted test and still fail regression, giving the controlled agent loop real evidence for a reflection iteration. A strong model may diagnose both defects before its first patch; the demo never forces a synthetic failure.

Run the unpatched baseline locally:

```bash
npm run test:targeted
npm test
```
