# Requirements Document

## Introduction

This document specifies the bulk discount feature for the pricing library. The feature provides automatic discounts for line items with quantities meeting a minimum threshold, encouraging larger purchases while maintaining pricing transparency.

## Requirements

### Requirement 1: Bulk Discount Rule

**User Story:** As a customer, I want to receive a 5% discount on line items with quantity of at least 10, so that I am incentivized to buy in bulk.

#### Acceptance Criteria

1. WHEN a line item has a quantity of exactly 10, THEN the system SHALL apply a 5% discount to that line item's total price.

2. WHEN a line item has a quantity of 9 or less, THEN the system SHALL NOT apply any bulk discount to that line item.

3. WHEN calculating the discount amount, THEN the system SHALL round the monetary value half-up to 0.01 precision.

### Requirement 2: Cart Bulk Savings Total

**User Story:** As a customer, I want to see the total savings from all bulk discounts in my cart, so that I understand the value I'm receiving.

#### Acceptance Criteria

1. WHEN the cart contains multiple line items with bulk discounts, THEN the system SHALL return the sum of all individual line item savings.

2. WHEN the cart is empty, THEN the system SHALL return a bulk savings total of zero.

3. WHEN the cart contains only line items without bulk discounts, THEN the system SHALL return a bulk savings total of zero.
