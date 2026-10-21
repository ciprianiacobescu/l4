# Proposal: shelf code

## Why
Pick lists print where a SKU sits as a short shelf code, and a shelf position below 1 is a data error.

## What Changes
- Add `inventory.shelf.shelf_code(aisle, slot)`, which returns `A<aisle>-S<slot>` with both numbers zero-padded to two
  digits (aisle 3, slot 7 gives `A03-S07`), and raises `ValueError` when the aisle or the slot is below 1.

## Capabilities

### New Capabilities
- `shelf-code`: the printed code of a shelf position.

### Modified Capabilities

## Impact
`src/inventory/shelf.py` (new), tests under `tests/`.
