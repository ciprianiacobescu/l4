# Spec Delta

## Purpose
The fee that an overdue balance carries.

## ADDED Requirements

### Requirement: Late fee
`billing.fees.late_fee_cents(balance_cents: int, days_late: int)` SHALL return `0` when `days_late` is 5 or fewer, and
otherwise 2 percent of `balance_cents` rounded half up to whole cents, and SHALL raise `ValueError` when `balance_cents`
is negative.

#### Scenario: Within the grace period there is no fee
- **WHEN** billing asks for `billing.fees.late_fee_cents(10000, 3)`
- **THEN** it returns `0`

#### Scenario: After the grace period the fee is a share of the balance
- **WHEN** billing asks for `billing.fees.late_fee_cents(10000, 9)`
- **THEN** it returns `200`
