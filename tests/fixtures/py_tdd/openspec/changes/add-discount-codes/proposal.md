## Why

Shoppers expect to enter a discount code at checkout, and today the pricing module cannot apply one.

## What Changes

- Add `pytdd.pricing.apply_discount(amount, code)` with the fixed code table `SAVE10` (10 % off).
- Unknown codes are rejected with `ValueError`.

## Impact

- New capability `pricing`; code in `src/pytdd/pricing.py`, tests in `tests/`.
