# Design Document

## Overview

The bulk discount feature introduces a quantity-based pricing rule that automatically applies a 5% discount to line items with a quantity of 10 or more units. The design separates concerns by creating a reusable bulk discount calculation module and extending the `Cart` class with a method to compute total bulk savings across all line items.

## Architecture

The implementation follows a modular architecture with two main components:

1. **Bulk Discount Rule Module**: A pure function that encapsulates the business logic for calculating bulk discount amounts for individual line items.
2. **Cart Extension**: The `Cart.bulk_savings()` method that aggregates bulk discounts across all line items.

This separation ensures the bulk discount logic is testable in isolation and reusable for other pricing scenarios.

## Components and Interfaces

### Bulk Discount Rule Module

**Location**: `src/pricing/bulk_discount.py`

**Function**: `calculate_bulk_discount(line_item: LineItem) -> Decimal`

- **Input**: A `LineItem` instance
- **Output**: A `Decimal` representing the discount amount (zero or positive)
- **Behavior**:
  - Returns `Decimal("0.00")` if quantity < 10
  - Calculates 5% of the line total if quantity >= 10
  - Rounds the result using `ROUND_HALF_UP` to 0.01

### Cart.bulk_savings() Method

**Location**: `src/pricing/cart.py`

**Method Signature**: `def bulk_savings(self) -> Decimal`

- **Input**: None (operates on `self.items`)
- **Output**: A `Decimal` representing total bulk savings across all line items
- **Behavior**:
  - Iterates over all items in the cart
  - Calls `calculate_bulk_discount()` for each item
  - Returns the sum of all discount amounts

## Data Models

No new data models are required. The implementation reuses the existing `LineItem` and `Cart` classes.

### LineItem

- Already contains `sku`, `unit_price`, `quantity`, and `total` property
- No modifications needed

### Cart

- Add `bulk_savings()` method
- No modifications to existing attributes

## Error Handling

The bulk discount calculation is deterministic and does not introduce new error conditions:

- Invalid `LineItem` instances (negative prices, zero quantity) are already prevented by existing validation in `LineItem.__post_init__`
- Empty cart returns `Decimal("0.00")` without error
- All `Decimal` arithmetic uses existing rounding behavior

## Testing Strategy

### Unit Tests

1. **Bulk Discount Rule Module**:
   - Quantity exactly 10 → 5% discount
   - Quantity > 10 → 5% discount
   - Quantity < 10 → zero discount
   - Rounding behavior with prices that produce fractional cents
   - Edge case: quantity = 0 (should not occur due to validation)

2. **Cart.bulk_savings() Method**:
   - Empty cart → Decimal("0.00")
   - Cart with only non-qualifying items → Decimal("0.00")
   - Cart with only qualifying items → correct sum
   - Cart with mixed items → correct sum of qualifying items only

### Property-Based Tests

- Property: `bulk_discount >= 0` for any valid line item
- Property: `bulk_discount <= line_item.total * 0.05` for any line item
- Property: sum of individual discounts equals `cart.bulk_savings()`

## Correctness Properties

1. **Non-negativity**: Bulk discount amounts are always >= 0
2. **Threshold Correctness**: Discount applies if and only if quantity >= 10
3. **Percentage Correctness**: Discount is exactly 5% of line total for qualifying items
4. **Rounding Correctness**: All discount amounts are rounded to 0.01 using half-up rounding
5. **Additivity**: Cart bulk savings equals the sum of individual line item discounts
6. **Empty Cart Invariant**: An empty cart has zero bulk savings
