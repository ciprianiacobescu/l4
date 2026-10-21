# Spec Delta

## Purpose
How many units of a SKU the weekly order asks for.

## ADDED Requirements

### Requirement: Reorder quantity
`inventory.reorder.reorder_quantity(on_hand: int, target: int)` SHALL return the `int` `target - on_hand` when
`on_hand` is below `target`, and `0` when `on_hand` is at or above `target`.

#### Scenario: Stock below the target is topped up
- **WHEN** the weekly order asks for `inventory.reorder.reorder_quantity(4, 10)`
- **THEN** it returns `6`

#### Scenario: Stock above the target is not ordered
- **WHEN** the weekly order asks for `inventory.reorder.reorder_quantity(12, 10)`
- **THEN** it returns `0`
