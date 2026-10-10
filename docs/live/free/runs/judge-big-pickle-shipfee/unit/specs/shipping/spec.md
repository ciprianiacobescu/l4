# Spec Delta

## Purpose
Shipping fees charged on an order, by destination country.

## ADDED Requirements

### Requirement: Shipping fee
`pricing.shipping.shipping_fee(subtotal, country)` SHALL return the shipping fee of an order as a `Decimal` quantized to 0.01 with ROUND_HALF_UP. `subtotal` is a `Decimal`; `country` is an ISO 3166-1 alpha-2 code matched exactly as given, so `ro` is not `RO`. The subtotal is checked first: a negative subtotal SHALL raise `ValueError`. The fee is 4.99 for `RO` and 9.99 for `DE`, and an order to `RO` or `DE` whose subtotal is 50.00 or more ships free (fee 0.00). Any other country SHALL raise `UnsupportedShippingCountry`, defined in `pricing.shipping`, whatever the subtotal.

#### Scenario: Romanian order below the free-shipping threshold
- **WHEN** an order with a subtotal of 20.00 ships to `RO`
- **THEN** the shipping fee is 4.99

#### Scenario: German order below the free-shipping threshold
- **WHEN** an order with a subtotal of 20.00 ships to `DE`
- **THEN** the shipping fee is 9.99
