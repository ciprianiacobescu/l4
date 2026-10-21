# Design Document

## Overview

The bulk discount feature introduces a quantity-based pricing rule that applies a 5% discount to line items with quantities of 10 or more. This design follows the Single Responsibility Principle by separating the discount calculation logic into a dedicated module and adding a single coordination method to the Cart class.

## Architecture

The implementation follows a modular approach:

1. **Bulk Discount Module**: A standalone module (`pricing.bulk_discount`) contains the core logic for determining if a line item qualifies for bulk discount and calculating the discount amount
2. **Cart Integration**: The `Cart` class exposes a `bulk_savings()` method that orchestrates the calculation across all line items

This separation allows the bulk discount logic to be tested independently and potentially reused in other contexts (e.g., order processing, reporting).

## Components and Interfaces

### BulkDiscountRule Module (`pricing/bulk_discount.py`)

**Constants:**
- `BULK_QUANTITY_THRESHOLD = 10`: The minimum quantity required for bulk discount eligibility
- `BULK_DISCOUNT_PERCENT = Decimal("5")`: The discount percentage applied to qualifying line items

**Functions:**

```python
def qualifies_for_bulk_discount(item: LineItem) -> bool
```
Returns `True` if the line item's quantity is at least `BULK_QUANTITY_THRESHOLD`.

```python
def calculate_bulk_discount(item: LineItem) -> Decimal
```
Returns the discount amount for a line item. If the item qualifies, returns 5% of the line total rounded half-up to 0.01. Otherwise returns `Decimal("0.00")`.

### Cart Extension

```python
def bulk_savings(self) -> Decimal
```
Returns the total bulk discount savings across all line items in the cart. Iterates over `self.items`, calls `calculate_bulk_discount` on each, and sums the results. Returns `Decimal("0.00")` for an empty cart.

## Data Models

No new data models are required. The feature operates on existing `LineItem` and `Cart` classes.

**LineItem properties used:**
- `quantity: int` — determines eligibility
- `total: Decimal` — the base amount for percentage calculation

**Cart properties used:**
- `items: list[LineItem]` — iterated to aggregate savings

## Error Handling

The feature does not introduce new error conditions. It relies on existing `LineItem` validation:
- `LineItem.__post_init__` ensures `quantity >= 1` and `unit_price >= 0`
- If these invariants hold, bulk discount calculations cannot fail

The `bulk_savings()` method handles empty carts gracefully by returning `Decimal("0.00")`.

## Testing Strategy

### Unit Tests

**BulkDiscountRule tests (`tests/test_bulk_discount.py`):**
1. Quantity threshold boundary: quantities 9, 10, 11
2. Discount calculation correctness with various prices
3. Rounding behavior with amounts that require half-up rounding (e.g., 0.125 → 0.13)
4. Non-qualifying items return zero discount

**Cart integration tests (added to `tests/test_cart.py`):**
1. `bulk_savings()` returns sum of qualifying line item discounts
2. Empty cart returns 0.00
3. Cart with no qualifying items returns 0.00
4. Cart with mixed qualifying and non-qualifying items returns correct sum

### Property Tests

Property-based test for `calculate_bulk_discount`:
- For any `LineItem` with `quantity >= 10`, the discount equals 5% of `item.total` rounded half-up
- For any `LineItem` with `quantity < 10`, the discount equals `Decimal("0.00")`
- The discount is always non-negative and at most 5% of the line total

## Correctness Properties

1. **Monotonicity**: For a fixed unit price, increasing quantity from 9 to 10 never decreases the customer's savings
2. **Idempotence**: Calling `bulk_savings()` multiple times on an unchanged cart returns the same value
3. **Non-negativity**: `bulk_savings()` always returns a value >= 0
4. **Precision**: All discount amounts are exactly representable as `Decimal` with scale 2
5. **Independence**: The bulk discount on one line item does not affect the bulk discount on another
6. **Threshold**: The discount is a step function at quantity 10, continuous elsewhere
