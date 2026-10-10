# Requirements Document

## Introduction

This document specifies the small-order surcharge feature for the pricing library. Orders with a subtotal below $20.00 will incur a $2.00 surcharge to cover handling costs for small orders. This feature consists of a standalone rule function and a cart method that applies the rule while handling the empty-cart edge case.

## Requirements

### Requirement 1

**User Story:** As a pricing system, I need to calculate the small-order surcharge based on a given subtotal so that orders below the minimum threshold incur the appropriate fee.

#### Acceptance Criteria

1. WHEN the subtotal is below 20.00 (for example 5.00) THEN the system SHALL return 2.00 as the surcharge.

2. WHEN the subtotal is 20.00 or more (for example 20.00 and 35.00) THEN the system SHALL return 0.00 as the surcharge.

3. WHEN the subtotal is 19.99 (just below the threshold) THEN the system SHALL return 2.00 as the surcharge.

### Requirement 2

**User Story:** As a shopping cart, I need to compute my own small-order surcharge by applying the rule to my subtotal so that the surcharge can be included in order totals.

#### Acceptance Criteria

1. WHEN the cart is non-empty and its subtotal is below 20.00 THEN the system SHALL return 2.00 as the surcharge, and WHEN the cart is non-empty and its subtotal is 20.00 or more THEN the system SHALL return 0.00 as the surcharge.

2. WHEN the cart is empty THEN the system SHALL return 0.00 as the surcharge.
