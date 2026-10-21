# Design Document

## Overview

The bulk discount feature extends the existing pricing library with automatic discounts for high-quantity purchases. The design introduces a discount calculation module that integrates with the existing `LineItem` and `Cart` classes without modifying their core data structures.

## Architecture

The feature follows a modular architecture with clear separation of concerns:

- **Discount Rule Module**: Contains the business logic for calculating bulk discounts
- **Cart Integration**: Adds a new method to the `Cart` class to aggregate savings
- **LineItem Extension**: Leverages existing `LineItem` data to compute individual savings

The discount calculation is stateless and pure, taking quantity and price as inputs and returning the discount amount.

## Components and Interfaces

### Bulk Discount Calculator

**Module**: `src/pricing/bulk_discount.py`

**Function**: `calculate_bulk_discount(quantity: int, line_total: Decimal) -> Decimal`

- **Input**: Line item quantity (integer), line total price (Decimal)
- **Output**: Discount amount (Decimal), rounded half-up to 0.01
- **Behavior**: Returns 5% of line_total if quantity >= 10, otherwise returns Decimal("0.00")

### Cart Extension

**Method**: `Cart.bulk_savings() -> Decimal`

- **Returns**: Sum of bulk discounts across all line items in the cart
- **Implementation**: Iterates through line items, applies discount calculation, accumulates results

## Data Models

No new data structures are required. The feature uses existing models:

- `LineItem`: Contains `quantity` and pricing information needed for discount calculation
- `Cart`: Contains collection of line items

The discount amount is computed on-demand rather than stored, ensuring consistency with current pricing data.

## Error Handling

- **Invalid Quantity**: If quantity is negative, treat as zero (no discount)
- **Invalid Price**: If line_total is negative, treat as zero (no discount)
- **Empty Cart**: Return Decimal("0.00") for bulk_savings()
- **Decimal Precision**: Use `ROUND_HALF_UP` quantization to 0.01

## Testing Strategy

### Unit Tests

- Test boundary conditions: quantity = 9, 10, 11
- Test rounding: prices that produce fractional cent discounts
- Test edge cases: zero quantity, zero price, empty cart
- Test accumulation: multiple qualifying and non-qualifying items

### Property Tests

- Property: bulk_savings() >= 0 for any valid cart
- Property: bulk_savings() <= sum of all line totals
- Property: increasing quantity from 9 to 10 increases or maintains total value for customer

## Correctness Properties

1. **Monotonicity**: For quantities >= 10, larger quantities never result in higher per-unit effective prices
2. **Idempotency**: Calling `bulk_savings()` multiple times returns the same result
3. **Composability**: Total cart savings equals the sum of individual line item savings
4. **Precision**: All monetary calculations maintain exactly 2 decimal places
5. **Threshold Behavior**: Discount applies if and only if quantity >= 10
