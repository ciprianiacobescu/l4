# Verification: openspec:add-split-amount: PASS (round 1)

traceability: not checked (M0)

- Base: `8d1780b81c04828391ab50536584c4d0915ceb92`
- Head: `0696cb7f5bc79730009cfcddfabd96fad8587f34`
- Implementer profiles: opencode-free
- Judge: claude-code (claude-opus-5-5), 1 call(s), prompt sha256 `ae6585ae2f41401e90e7d3c7701d85ef81c63a9b0f7428c03569d2806340e1e6`
- independence: declared (unverified): claude-code anthropic (served claude-opus-5-5), opencode-free zhipu (declared)
- Cost: $0.1308

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | ok | 0.4 |  |
| 1 | integrity | not_run | 0.0 | not implemented in M0 (M1: verifier 2.x) |
| 2 | build | ok | 0.1 |  |
| 3 | tests | ok | 0.3 |  |
| 4 | traceability | not_run | 0.0 | not implemented in M0 (M1: verifier 1.9) |
| 9 | judge | ok | 27.1 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | PASS |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261004T1710Z-d68f/012-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261004T1710Z-d68f/013-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261004T1710Z-d68f/014-test.log |

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-f9d3de63 | bill-split › Split an amount into equal parts › Ten into three | pass | pass | the judge passed it |
| C-380cc1c1 | bill-split › Split an amount into equal parts › Even split | pass | pass | the judge passed it |
| C-def5ffbb | bill-split › Split an amount into equal parts › One cent in two parts | pass | pass | the judge passed it |
| C-9179b0c9 | bill-split › Split an amount into equal parts › Zero parts | pass | pass | the judge passed it |
| C-e48840fe | bill-split › Split an amount into equal parts › Negative amount | pass | pass | the judge passed it |

## Findings

- [minor, judge] Tiny negative amounts that round to zero are rejected (spec gap): Decimal('-0.004') < 0 is True, so the function raises ValueError even though the amount quantizes to -0.00 with ROUND_HALF_UP. Another reasonable implementation would quantize first and accept it. No scenario pins this down.
- [minor, judge] Non-Decimal or non-integer inputs are not validated (spec gap): An int or float amount fails with AttributeError because those types have no .quantize. A NaN amount fails with InvalidOperation on the comparison. A non-integer parts value such as 2.5 makes range() raise TypeError. The spec does not say which error these cases should raise, so two implementations could differ.
- [minor, judge] Tests do not enforce the two-decimal exponent: Decimal equality ignores the exponent, so a result like Decimal('3') would still pass the tests. The implementation does produce exponent -2 through scaleb(-2), but no test guards that.

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_split::test_split_amount_even_split_gives_equal_parts` (task 1.1): passed
- `tests.test_split::test_split_amount_one_cent_into_two_parts_gives_the_cent_to_one_part` (task 1.1): passed
- `tests.test_split::test_split_amount_rejects_negative_amount` (task 1.1): passed
- `tests.test_split::test_split_amount_rejects_zero_parts` (task 1.1): passed
- `tests.test_split::test_split_amount_ten_into_three_puts_larger_parts_first` (task 1.1): passed
