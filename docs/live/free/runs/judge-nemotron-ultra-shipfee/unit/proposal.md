# Proposal: shipping fee

## Why
Checkout must show what shipping costs before the customer pays, and the fee depends on the country the order ships to.

## What Changes
- Add `pricing.shipping.shipping_fee(subtotal, country)` and the exception `UnsupportedShippingCountry`.

## Capabilities

### New Capabilities
- `shipping`: shipping fees by destination country.

### Modified Capabilities

## Impact
New module `src/pricing/shipping.py`, its exports in `src/pricing/__init__.py`, tests under `tests/`.
