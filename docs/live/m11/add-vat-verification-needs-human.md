# Verification: openspec:add-vat: NEEDS_HUMAN (round 1)

traceability: not checked (M0)

- Base: `dd36ab8fe11a8d479cc45331a6d39923278fbb09`
- Head: `ea6c16d5c1cbd652db1f006788d35a0f51688d50`
- Implementer profiles: codex
- Judge: claude-code (claude-opus-5-5), 1 call(s), prompt sha256 `6a3244bd3fd46d7ef9de8c6006bbc1187f10d454fb69c0845c80ce445477de71`
- Cost: $0.1294

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | ok | 0.5 |  |
| 1 | integrity | not_run | 0.0 | not implemented in M0 (M1: verifier 2.x) |
| 2 | build | ok | 0.1 |  |
| 3 | tests | ok | 0.3 |  |
| 4 | traceability | not_run | 0.0 | not implemented in M0 (M1: verifier 1.9) |
| 9 | judge | ok | 21.6 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | NEEDS_HUMAN |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261004T1050Z-8338/023-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261004T1050Z-8338/024-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261004T1050Z-8338/025-test.log |

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-5427d9c3 | vat › VAT by country › Romanian customer, current rate | pass | pass | the judge passed it |
| C-3d5b62ab | vat › VAT by country › German customer | pass | pass | the judge passed it |
| C-e28fa9b2 | vat › VAT by country › Unsupported country | pass | pass | the judge passed it |

## Findings

- [major, judge] VAT ignores any applied discount code (spec gap): total_with_vat starts from self.subtotal() and never uses the discounted total that Cart.total() computes. If a discount code has been applied, the VAT total is worked out on the pre-discount amount, so a customer would pay VAT on money they were not charged. The proposal says 'the cart total shown to the customer includes VAT', but the requirement says 'cart subtotal plus VAT', and no scenario covers a discounted cart. Two reasonable implementations give different answers. Example: with 10% off and RO, the committed code gives 121.00, while VAT on the discounted total gives 108.90.
- [minor, judge] Country code lookup is case-sensitive (spec gap): vat_rate('ro') raises UnsupportedCountry. Discount-code lookup in the same package is case-insensitive (test_discount_registry_lookup_is_case_insensitive). ISO 3166-1 alpha-2 codes are upper case by convention, but the spec doesn't say whether lower-case input should be accepted.

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_vat::test_cart_total_with_vat_for_supported_countries[DE-expected_total1]` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_for_supported_countries[RO-expected_total0]` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_rejects_unsupported_country` (task 1.2): passed
- `tests.test_vat::test_vat_rate_is_defined_for_supported_countries[DE-expected_rate1]` (task 1.1): passed
- `tests.test_vat::test_vat_rate_is_defined_for_supported_countries[RO-expected_rate0]` (task 1.1): passed
- `tests.test_vat::test_vat_rate_rejects_unsupported_country` (task 1.1): passed
