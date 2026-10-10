# Design Document

## Overview

The small-order surcharge feature introduces a pricing rule that charges a fixed $2.00 surcharge on orders with subtotals below $20.00. This is implemented as a pure function in a new `surcharge` module and integrated into the `Cart` class as a method.

## Architecture

The feature follows a separation-of-concerns pattern:

- **Rule layer**: A pure function `small_order_surcharge` encapsulates the threshold logic
- **Domain layer**: The `Cart` class applies the rule to its own subtotal with empty-cart awareness

This design keeps the pricing rule testable in isolation and allows the cart to add domain-specific logic (empty-cart handling).

## Components and Interfaces

### `src/pricing/surcharge.py`

A new module containing the core surcharge logic.

**Function**: `small_order_surcharge(subtotal: Decimal) -> Decimal`

- **Input**: `subtotal` — a `Decimal` representing the order subtotal with two decimal places
- **Output**: A `Decimal` representing the surcharge amount (2.00 or 0.00)
- **Logic**: Returns `Decimal("2.00")` if `subtotal < Decimal("20.00")`, otherwise `Decimal("0.00")`

This function is stateless and has no side effects. It must be added to `__all__` in `src/pricing/__init__.py` per project conventions.

### `src/pricing/cart.py` (modification)

**Method**: `Cart.small_order_surcharge() -> Decimal`

- **Output**: A `Decimal` representing the surcharge for this cart
- **Logic**: 
  - If the cart is empty, return `Decimal("0.00")`
  - Otherwise, call `small_order_surcharge(self.subtotal())`

The method delegates the threshold logic to the surcharge module while handling the empty-cart special case.

## Data Models

All monetary values are represented as `Decimal` with two decimal places, consistent with the existing `Cart` and `LineItem` implementation.

- **Threshold**: `Decimal("20.00")`
- **Surcharge amount**: `Decimal("2.00")`
- **No surcharge**: `Decimal("0.00")`

## Error Handling

No special error handling is required. The function assumes valid `Decimal` input. Invalid types or values are the caller's responsibility.

## Testing Strategy

### Unit Tests

**Rule function tests** (`test_surcharge.py` or within existing test files):
- Test subtotal below threshold (e.g., 5.00 → 2.00)
- Test subtotal at threshold (20.00 → 0.00)
- Test subtotal above threshold (e.g., 35.00 → 0.00)
- Test edge case: 19.99 → 2.00

**Cart method tests** (within existing cart test files):
- Test non-empty cart with subtotal below threshold → 2.00
- Test non-empty cart with subtotal at or above threshold → 0.00
- Test empty cart → 0.00

### Property-Based Tests (Optional)

Use hypothesis to verify:
- All subtotals below 20.00 return exactly 2.00
- All subtotals >= 20.00 return exactly 0.00
- Output is always one of {0.00, 2.00}

## Correctness Properties

1. **Threshold invariant**: The surcharge is 2.00 if and only if the subtotal is strictly less than 20.00
2. **Boundary correctness**: 19.99 returns 2.00; 20.00 returns 0.00
3. **Empty cart rule**: An empty cart always returns 0.00 regardless of the rule
4. **Determinism**: Same subtotal always produces the same surcharge
5. **Type safety**: All monetary values are `Decimal` with two decimal places
