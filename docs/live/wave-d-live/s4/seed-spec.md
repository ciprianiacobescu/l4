# Spec Delta

## Purpose
The price of a cart line under the three-for-two offer.

## ADDED Requirements

### Requirement: Every third unit is free
`pricing.offers.three_for_two(unit_price: Decimal, quantity: int)` SHALL return a `Decimal` with two decimal places:
the price of `quantity - quantity // 3` units. A negative `quantity` SHALL raise `ValueError`.

#### Scenario: Three units cost two
- **WHEN** the shop calls `pricing.offers.three_for_two(Decimal("2.00"), 3)`
- **THEN** it returns `Decimal("4.00")`

#### Scenario: Seven units cost five
- **WHEN** the shop calls `pricing.offers.three_for_two(Decimal("2.00"), 7)`
- **THEN** it returns `Decimal("10.00")`

#### Scenario: A negative quantity is refused
- **WHEN** the shop calls `pricing.offers.three_for_two(Decimal("2.00"), -1)`
- **THEN** it raises `ValueError`
