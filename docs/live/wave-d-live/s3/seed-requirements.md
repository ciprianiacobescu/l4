# Requirements Document

## Introduction

Customers can ask for their items to be gift wrapped. Wrapping costs 1.50 per wrapped unit. This feature adds a
standalone fee rule and a cart method that applies it to the units of the SKUs the customer asked to wrap.

## Requirements

### Requirement 1

**User Story:** As the pricing system, I need the gift-wrap fee for a number of wrapped units so that wrapping is
charged per unit.

#### Acceptance Criteria

1.1. WHEN `gift_wrap_fee(3)` is called THEN the system SHALL return `Decimal("4.50")`.

1.2. WHEN `gift_wrap_fee(0)` is called THEN the system SHALL return `Decimal("0.00")`.

1.3. WHEN `gift_wrap_fee` is called with a negative number of units (for example -1) THEN the system SHALL raise `ValueError`.

### Requirement 2

**User Story:** As a shopping cart, I need the gift-wrap fee of the SKUs the customer asked to wrap so that it can be
shown with the order total.

#### Acceptance Criteria

2.1. WHEN the cart holds 2 units of SKU "A" and 1 unit of SKU "B" and `Cart.gift_wrap_fee({"A"})` is called THEN the system SHALL return `Decimal("3.00")`.

2.2. WHEN `Cart.gift_wrap_fee` is called with a set of SKUs that the cart does not hold (for example an empty cart and `{"A"}`) THEN the system SHALL return `Decimal("0.00")`.
