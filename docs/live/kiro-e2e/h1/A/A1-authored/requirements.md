# Requirements Document

## Introduction

This document specifies requirements for a bulk discount feature in the pricing library. Line items with a quantity of at least 10 will receive a 5% discount on their line total. The discount amount is calculated with half-up rounding to two decimal places. The `Cart` class will expose a `bulk_savings()` method that returns the total savings across all line items.

## Requirements

### Requirement 1

**User Story:** As a customer, I want to receive a 5% discount on line items when I purchase 10 or more units, so that I save money on bulk purchases.

#### Acceptance Criteria

1. WHEN a line item has a quantity of exactly 10 THEN the system SHALL apply a 5% discount to that line item's total.
2. WHEN a line item has a quantity greater than 10 THEN the system SHALL apply a 5% discount to that line item's total.
3. WHEN a line item has a quantity of 9 or fewer THEN the system SHALL NOT apply any bulk discount to that line item.
4. WHEN calculating the bulk discount amount THEN the system SHALL round the discount using half-up rounding to 0.01 (two decimal places).

### Requirement 2

**User Story:** As a customer, I want to see how much I've saved from bulk discounts, so that I understand the value of my bulk purchases.

#### Acceptance Criteria

1. WHEN the `Cart.bulk_savings()` method is called THEN the system SHALL return the sum of all bulk discount amounts from all line items in the cart.
2. WHEN the cart is empty THEN the system SHALL return Decimal("0.00") for bulk savings.
3. WHEN the cart contains only line items that do not qualify for bulk discount THEN the system SHALL return Decimal("0.00") for bulk savings.
4. WHEN the cart contains a mix of qualifying and non-qualifying line items THEN the system SHALL sum only the savings from qualifying line items.
