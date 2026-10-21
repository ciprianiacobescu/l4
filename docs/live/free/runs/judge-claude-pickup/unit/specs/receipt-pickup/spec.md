# Spec Delta

## Purpose
The pickup rule that receipts print.

## ADDED Requirements

### Requirement: Pickup notice
`pricing.pickup.pickup_notice()` SHALL return a `str` equal to exactly
`Pickup orders wait at the shop counter for seven days; bring the order number and a photo ID.`

#### Scenario: The pickup notice text is exact
- **WHEN** the receipt footer calls `pricing.pickup.pickup_notice()`
- **THEN** it returns exactly `Pickup orders wait at the shop counter for seven days; bring the order number and a photo ID.`
