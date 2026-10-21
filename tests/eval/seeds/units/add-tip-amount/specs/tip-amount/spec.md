# Spec Delta

## Purpose
The tip, in whole cents, that the checkout adds for a percentage of the cart total.

## ADDED Requirements

### Requirement: Tip in whole cents
`pricing.tips.tip_cents(total_cents: int, percent: int)` SHALL return an `int`: `total_cents * percent / 100` rounded
half up to whole cents.

#### Scenario: A tip that is already whole cents
- **WHEN** the checkout calls `pricing.tips.tip_cents(1000, 15)`
- **THEN** it returns `150`

#### Scenario: A half cent rounds up
- **WHEN** the checkout calls `pricing.tips.tip_cents(1005, 10)`
- **THEN** it returns `101`
