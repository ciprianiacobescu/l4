# Verification: openspec:add-discount-codes: PASS (round 1)

traceability: not checked (M0)

- Base: `e1db758cc78aaf7f2884de0a24e2230a6be893f4`
- Head: `bca83856e61ac840c2370e49350afcbd5bfa3904`
- Implementer profiles: codex
- Judge: claude-code (claude-opus-5-5), 1 call(s), prompt sha256 `6a1dcbf0809807265817f3085fd8a84574627e4638b0a5471c43277d2601700d`
- Cost: $0.1615

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | ok | 0.5 |  |
| 1 | integrity | not_run | 0.0 | not implemented in M0 (M1: verifier 2.x) |
| 2 | build | ok | 0.1 |  |
| 3 | tests | ok | 0.3 |  |
| 4 | traceability | not_run | 0.0 | not implemented in M0 (M1: verifier 1.9) |
| 9 | judge | ok | 33.0 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | PASS |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261004T0105Z-abfc/023-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261004T0105Z-abfc/024-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261004T0105Z-abfc/025-test.log |

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-d397b698 | discounts › Discount code registry › Case-insensitive lookup | pass | pass | the judge passed it |
| C-9ea42110 | discounts › Discount code registry › Unknown code | pass | pass | the judge passed it |
| C-88f551b4 | discounts › Discount code registry › Invalid percentage rejected | pass | pass | the judge passed it |
| C-5a04eb51 | discounts › Applying a code to a cart › Percentage discount | pass | pass | the judge passed it |
| C-643facb9 | discounts › Applying a code to a cart › Fixed amount discount | pass | pass | the judge passed it |
| C-7c3bfae8 | discounts › Applying a code to a cart › Second code replaces the first | pass | pass | the judge passed it |
| C-6629b33a | discounts › Total is never negative › Amount larger than subtotal | pass | pass | the judge passed it |

## Findings

- [minor, judge] Spec doesn't say whether to round the discount or the final total (spec gap): total() applies ROUND_HALF_UP once, to the discounted total. Another reasonable reading rounds the discount amount first and then subtracts it. The two give different answers when the subtotal is 0.05 and the code is PercentOff(10): rounding the total gives 0.045 -> 0.05, while rounding the discount gives 0.005 -> 0.01 off, so 0.04. No scenario covers this.
- [minor, judge] Spec doesn't say what an unknown code does to a discount already applied (spec gap): apply_code calls lookup before assigning, so an UnknownDiscountCode leaves the earlier discount in place. Another implementation could clear it instead. No scenario covers this.
- [minor, judge] Spec doesn't say what happens when a code is registered twice (spec gap): register silently replaces an existing code, including one that differs only in case ("save10" after "SAVE10"). Another implementation could reject the duplicate. No scenario covers this.
- [minor, judge] A NaN percent or amount raises InvalidOperation, not ValueError (spec gap): With PercentOff(Decimal('NaN')), the chained comparison raises decimal.InvalidOperation, which is not a ValueError, so this invalid discount isn't rejected with ValueError as the requirement says. A non-numeric string fails the same way, in the Decimal(str(...)) conversion. No scenario covers these inputs.

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_cart::test_apply_code_raises_for_unknown_code` (task 1.2): passed
- `tests.test_cart::test_applying_second_code_replaces_first` (task 1.2): passed
- `tests.test_cart::test_cart_total_never_goes_below_zero` (task 1.2): passed
- `tests.test_cart::test_cart_total_rounds_half_up_to_cents` (task 1.2): passed
- `tests.test_cart::test_cart_total_uses_fixed_amount_discount` (task 1.2): passed
- `tests.test_cart::test_cart_total_uses_percentage_discount` (task 1.2): passed
- `tests.test_discounts::test_discount_registry_lookup_is_case_insensitive` (task 1.1): passed
- `tests.test_discounts::test_discount_registry_raises_for_unknown_code` (task 1.1): passed
- `tests.test_discounts::test_registering_invalid_percentage_raises_value_error[0]` (task 1.1): passed
- `tests.test_discounts::test_registering_invalid_percentage_raises_value_error[150]` (task 1.1): passed
