# Proposal: pickup notice

## Why
The receipt footer must print the shop's pickup rule word for word, as approved.

## What Changes
- Add `pricing.pickup.pickup_notice()`, which returns exactly
  `Pickup orders wait at the shop counter for seven days; bring the order number and a photo ID.`

## Capabilities

### New Capabilities
- `receipt-pickup`: the pickup rule printed on receipts.

### Modified Capabilities

## Impact
`src/pricing/pickup.py` (new), tests under `tests/`.
