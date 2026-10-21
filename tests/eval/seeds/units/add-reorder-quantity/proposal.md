# Proposal: reorder quantity

## Why
The weekly order tops every SKU up to its target stock, and a SKU already at or above its target must not be ordered.

## What Changes
- Add `inventory.reorder.reorder_quantity(on_hand, target)`, which returns `target - on_hand` when the stock on hand is
  below the target, and `0` otherwise.

## Capabilities

### New Capabilities
- `reorder-quantity`: how many units of a SKU the weekly order asks for.

### Modified Capabilities

## Impact
`src/inventory/reorder.py` (new), tests under `tests/`.
