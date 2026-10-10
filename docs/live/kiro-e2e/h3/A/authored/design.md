# Design Document

## Overview

The small-order surcharge feature adds a $2.00 handling fee to orders with subtotals below $20.00. The design separates the pure pricing rule from cart-specific logic, enabling reuse and simplifying testing.

## Architecture

The feature consists of two components:

1. **Rule Module** (`src/pricing/surcharge.py`): A standalone module containing the threshold-based surcharge calculation
2. **Cart Method** (`Cart.small_order_surcharge()`): A cart-aware method that applies the rule with empty-cart handling

This separation follows the existing pattern in the pricing library where pure calculation functions exist independently of domain objects.

## Components and Interfaces

### `src/pricing/surcharge.py`

**Function:** `small_order_surcharge(subtotal: Decimal) -> Decimal`

- **Input:** `subtotal` - A `Decimal` representing the order subtotal with two decimal places
- **Output:** A `Decimal` with two decimal places representing the surcharge amount (2.00 or 0.00)
- **Logic:** Returns `Decimal("2.00")` if `subtotal < Decimal("20.00")`, otherwise returns `Decimal("0.00")`

### `Cart.small_order_surcharge()`

**Method:** `Cart.small_order_surcharge(self) -> Decimal`

- **Input:** Implicit (operates on the cart's own state)
- **Output:** A `Decimal` with two decimal places representing the surcharge amount
- **Logic:** 
  - If the cart is empty, returns `Decimal("0.00")` directly
  - Otherwise, calls `small_order_surcharge(self.subtotal())` and returns the result

## Data Models

All monetary values are represented as `Decimal` objects with two decimal places, consistent with the existing `Cart` and `LineItem` implementation.

**Constants:**
- Threshold: `Decimal("20.00")`
- Surcharge amount: `Decimal("2.00")`
- No surcharge: `Decimal("0.00")`

**Cart state determination:**
- A cart is considered empty when it contains no line items (length check or equivalent)

## Error Handling

No special error handling is required. The function assumes valid `Decimal` inputs. Invalid inputs (negative subtotals, None values) are outside the scope of this feature and should be prevented by the calling code or handled by existing cart validation.

## Testing Strategy

### Unit Tests for Rule Module

Test `small_order_surcharge()` with:
- Subtotal below threshold (e.g., 5.00) → expects 2.00
- Subtotal at threshold (20.00) → expects 0.00
- Subtotal above threshold (e.g., 35.00) → expects 0.00
- Subtotal just below threshold (19.99) → expects 2.00

### Unit Tests for Cart Method

Test `Cart.small_order_surcharge()` with:
- Non-empty cart with subtotal below 20.00 → expects 2.00
- Non-empty cart with subtotal at or above 20.00 → expects 0.00
- Empty cart → expects 0.00

### Property Tests (Optional)

Property-based tests can verify that:
- For all subtotals in [0, 19.99], surcharge equals 2.00
- For all subtotals >= 20.00, surcharge equals 0.00
- Surcharge is always non-negative
- Surcharge is always either 0.00 or 2.00 (no intermediate values)

## Correctness Properties

1. **Threshold Correctness:** The surcharge transitions from 2.00 to 0.00 exactly at the 20.00 boundary
2. **Monotonicity:** As subtotal increases, surcharge never increases (non-increasing function)
3. **Empty Cart Safety:** An empty cart never incurs a surcharge regardless of the rule's output
4. **Precision:** All monetary calculations preserve two decimal places
5. **Idempotency:** Multiple calls with the same subtotal always return the same surcharge
