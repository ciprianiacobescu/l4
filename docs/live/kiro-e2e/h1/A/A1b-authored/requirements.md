# Requirements Document

## Introduction

This feature adds a bulk discount mechanism to the pricing library. When a line item has a quantity of at least 10 units, the customer receives a 5% discount on that line's total. The cart will expose a new method to calculate the total savings from all bulk discounts applied across its line items.

## Requirements

### Requirement 1

**User Story:** As a customer, I want to receive a 5% discount on line items with quantities of 10 or more, so that I save money when buying in bulk.

#### Acceptance Criteria

1. WHEN a line item has a quantity of exactly 10 THEN the system SHALL apply a 5% discount to that line item's total
2. WHEN a line item has a quantity greater than 10 THEN the system SHALL apply a 5% discount to that line item's total
3. WHEN a line item has a quantity of 9 or fewer THEN the system SHALL NOT apply any bulk discount to that line item
4. WHEN calculating the bulk discount amount THEN the system SHALL round the discount to 0.01 using half-up rounding

### Requirement 2

**User Story:** As a customer, I want to see my total bulk savings across all items in my cart, so that I understand how much I'm saving through bulk purchases.

#### Acceptance Criteria

1. WHEN the cart contains line items with quantities of at least 10 THEN the system SHALL sum the individual bulk discounts from all qualifying line items
2. WHEN the cart contains no line items with quantities of at least 10 THEN the system SHALL return a bulk savings of 0.00
3. WHEN the cart is empty THEN the system SHALL return a bulk savings of 0.00
4. WHEN calculating total bulk savings THEN the system SHALL return the amount as a Decimal rounded to 0.01 using half-up rounding
