# Proposal: late fee

## Why
Overdue invoices carry a late fee that grows with what is owed, after a short grace period.

## What Changes
- Add `billing.fees.late_fee_cents(balance_cents, days_late)`, which returns `0` for 5 days late or fewer, and
  otherwise 2 percent of the balance, rounded half up to whole cents. A negative balance raises `ValueError`.

## Capabilities

### New Capabilities
- `late-fee`: the fee on an overdue balance.

### Modified Capabilities

## Impact
`src/billing/fees.py` (new), tests under `tests/`.
