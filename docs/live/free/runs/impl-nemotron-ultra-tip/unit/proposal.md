# Proposal: tip amount

## Why
The checkout offers a tip as a percentage of the cart total, and the tip must be a whole number of cents.

## What Changes
- Add `pricing.tips.tip_cents(total_cents, percent)`, which returns the tip in whole cents: `total_cents * percent / 100`
  rounded half up (a half cent goes up, so 100.5 cents becomes 101).

## Capabilities

### New Capabilities
- `tip-amount`: the tip in whole cents for a cart total and a percentage.

### Modified Capabilities

## Impact
`src/pricing/tips.py` (new), tests under `tests/`.
