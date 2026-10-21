# Verification: openspec:add-vat: FAIL (round 2)

traceability: 0/3 criteria covered by a discriminating test

- Base: `bb5f34771042df85daf273a0027ac9c0f7430d80`
- Head: `9e778f64271c4438b0e02ec0c5c442640684d1ef`
- Implementer profiles: codex
- Judge: claude-code (claude-opus-5-5), 1 call(s), prompt sha256 `7bd5f9fb730a6cb4d4e710c832d99eebb205066297dc8d62dd885fd9fadd3035`
- independence: verified (different_vendor): claude-code anthropic (served claude-opus-5-5), codex openai (tool)
- Cost: $0.1639

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | ok | 0.4 |  |
| 1 | integrity | ok | 0.1 | 6 sub-checks |
| 2 | build | ok | 1.0 |  |
| 3 | tests | ok | 0.5 |  |
| 4 | traceability | ok | 0.0 | 0/3 criteria covered |
| 4a | audit sampling | not_run | 0.0 | roles.verifier_agent is empty |
| 9 | judge | ok | 29.7 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | FAIL |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261005T0003Z-3ffd/001-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261005T0003Z-3ffd/002-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261005T0003Z-3ffd/003-test.log |

## Integrity

| Check | Status | Note |
|---|---|---|
| protected paths | ok | no protected path differs from the base |
| pre-existing tests | ok | 1 test file(s) compared with the base |
| red-green freeze | ok | 2 task(s): red and green compared |
| content scan | ok | no result-manipulating construct in the changed support and runner files |
| suppressions | skipped | no new suppression comment |
| tdd history | ok | 2 task(s); red tests passing at head: step 3 |

## Traceability

| Id | Criterion | State | Tests (status, proof) | Not evidence |
|---|---|---|---|---|
| C-5427d9c3 | vat › VAT by country › Romanian customer, current rate | uncovered | - | - |
| C-3d5b62ab | vat › VAT by country › German customer | uncovered | - | - |
| C-e28fa9b2 | vat › VAT by country › Unsupported country | uncovered | - | - |

## Human verdicts

- Q-002 reject F-366420f0 by human: WHEN a 10 % discount code is applied to a RO cart with subtotal 100.00 THEN total_with_vat is 108.90

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-5427d9c3 | vat › VAT by country › Romanian customer, current rate | pass | needs_human | uncovered: no adequate discriminating test traces it |
| C-3d5b62ab | vat › VAT by country › German customer | pass | needs_human | uncovered: no adequate discriminating test traces it |
| C-e28fa9b2 | vat › VAT by country › Unsupported country | pass | needs_human | uncovered: no adequate discriminating test traces it |

## Findings

- [major, judge] The owner's answer on discounts (Q-002) is not implemented: VAT is still computed on the pre-discount subtotal (criterion C-5427d9c3): In questions.md Q-002 the owner answered 'reject: WHEN a 10 % discount code is applied to a RO cart with subtotal 100.00 THEN total_with_vat is 108.90'. The committed total_with_vat still uses self.subtotal() and ignores Cart.total(), so that case returns 121.00, not 108.90. The spec text ('cart subtotal plus VAT') was not updated, and no scenario or test covers a discounted cart. Under the questions protocol a rejected finding goes to a fix unit, so this does not fail the three listed criteria. The behaviour the owner asked for is still missing, though.
- [minor, judge] Country code lookup is case-sensitive (spec gap) (criterion C-e28fa9b2): vat_rate looks the code up directly in _VAT_RATES, so 'ro' or ' RO' raises UnsupportedCountry. Discount-code lookup in the same package is case-insensitive (tests.test_discounts::test_discount_registry_lookup_is_case_insensitive). The spec only says the code is ISO 3166-1 alpha-2, so a reasonable implementation could normalise case either way.
- [major, human] VAT ignores any applied discount code (spec gap): total_with_vat starts from self.subtotal() and never uses the discounted total that Cart.total() computes. If a discount code has been applied, the VAT total is worked out on the pre-discount amount, so a customer would pay VAT on money they were not charged. The proposal says 'the cart total shown to the customer includes VAT', but the requirement says 'cart subtotal plus VAT', and no scenario covers a discounted cart. Two reasonable implementations give different answers. Example: with 10% off and RO, the committed code gives 121.00, while VAT on the discounted total gives 108.90. [rejected ...

## Fix unit

Fix unit 1 is created for these tasks:
- F-366420f0 VAT ignores any applied discount code

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_vat::test_cart_total_with_vat_for_supported_countries[DE-expected_total1]` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_for_supported_countries[RO-expected_total0]` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_rejects_unsupported_country` (task 1.2): passed
- `tests.test_vat::test_vat_rate_is_defined_for_supported_countries[DE-expected_rate1]` (task 1.1): passed
- `tests.test_vat::test_vat_rate_is_defined_for_supported_countries[RO-expected_rate0]` (task 1.1): passed
- `tests.test_vat::test_vat_rate_rejects_unsupported_country` (task 1.1): passed
