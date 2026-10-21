# Requirements Document

## Introduction

This document specifies the small-order surcharge feature for the pricing library. Orders with a subtotal below $20.00 will incur a $2.00 surcharge to cover handling costs. This surcharge applies only to non-empty carts and only when the subtotal is below the threshold.

## Requirements

### Requirement 1

**User Story:** As a pricing system, I need to calculate a small-order surcharge based on the order subtotal so that orders below $20.00 pay a $2.00 surcharge while larger orders pay none.

#### Acceptance Criteria

1.1. WHEN the subtotal is below 20.00 (for example 5.00) THEN the system SHALL return a surcharge of 2.00.

1.2. WHEN the subtotal is 20.00 or more (for example 20.00 and 35.00) THEN the system SHALL return a surcharge of 0.00.

1.3. WHEN the subtotal is 19.99 THEN the system SHALL return a surcharge of 2.00.

### Requirement 2

**User Story:** As a cart, I need to apply the small-order surcharge rule to my subtotal so that customers are charged appropriately, with special handling for empty carts.

#### Acceptance Criteria

2.1. WHEN the cart is non-empty and the subtotal is below 20.00 THEN the system SHALL return a surcharge of 2.00, and WHEN the cart is non-empty and the subtotal is 20.00 or more THEN the system SHALL return a surcharge of 0.00.

2.2. WHEN the cart is empty THEN the system SHALL return a surcharge of 0.00.
