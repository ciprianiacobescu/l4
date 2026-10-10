## ADDED Requirements

### Requirement: Discount codes
The `apply_discount(amount, code)` function SHALL return `amount` reduced by the percentage of a known code, rounded to
two decimals, and SHALL raise `ValueError` for a code that is not in the table. The table holds `SAVE10` (10 %).

#### Scenario: Known code
- **WHEN** `apply_discount(50.0, "SAVE10")` is called
- **THEN** it returns `45.0`

#### Scenario: Unknown code
- **WHEN** `apply_discount(50.0, "NOPE")` is called
- **THEN** it raises `ValueError`
