# Design Document

## Overview

The low stock message feature introduces a new alerts module to the inventory package. This module provides a single pure function that generates human-readable messages when inventory levels fall below a predefined threshold of 5 units.

## Architecture

The feature extends the existing inventory system with a new alerts module. The design follows a functional approach with no state or dependencies on other modules, making it simple to test and maintain.

```
src/inventory/
├── __init__.py
├── stock.py          (existing)
└── alerts.py         (new)
```

## Components and Interfaces

### `src/inventory/alerts.py`

**Function:** `low_stock_message(name: str, on_hand: int) -> str | None`

**Purpose:** Generate a low stock alert message when inventory falls below threshold.

**Parameters:**
- `name`: The name of the inventory item (e.g., "bolts")
- `on_hand`: The current quantity of the item in stock

**Returns:**
- A formatted message string when `on_hand < 5`
- `None` when `on_hand >= 5`

**Raises:**
- `ValueError` when `on_hand < 0`

**Message Format:** `Restock <name>: <on_hand> left`

**Threshold:** Fixed constant of 5 units

## Data Models

No new data structures are required. The function operates on primitive types:
- `name`: string identifier for the inventory item
- `on_hand`: integer quantity, must be non-negative

## Error Handling

The function validates input to ensure data integrity:
- Negative `on_hand` values are rejected immediately with `ValueError`
- The error message should clearly indicate the invalid input
- No other exceptions are expected from this pure function

## Testing Strategy

Unit tests will be implemented in `tests/test_alerts.py` covering:

1. **Below-threshold cases:** Verify correct message format for values 0-4
2. **At-threshold and above:** Verify `None` is returned for values >= 5
3. **Edge cases:** Zero inventory, boundary value at threshold (5)
4. **Validation:** Negative values raise `ValueError`

Test data should include representative item names and various inventory levels.

## Correctness Properties

The function must satisfy these invariants:
- For all valid `on_hand >= 0`: result is deterministic based solely on inputs
- For `on_hand < 5`: output message contains the exact `name` and `on_hand` values
- For `on_hand >= 5`: output is always `None`
- For `on_hand < 0`: raises `ValueError` before any other processing
- The function has no side effects (pure function)
