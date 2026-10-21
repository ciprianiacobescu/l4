# Verification: openspec:add-money-format: PASS (round 1)

traceability: not checked (M0)

- Base: `8b3347d29bb10895cc28afee8686ab9e6ad9e791`
- Head: `97014dc87275835e8970890ac19d6b2b1faea7e9`
- Implementer profiles: codex
- Judge: opencode-free, 1 call(s), prompt sha256 `78d1a0e79ca58d633c6d393ca56946fd7ede1353d9a4205c5e50d69f8d105d91`
- independence: declared (unverified): opencode-free zhipu (declared), codex openai (tool)
- Cost: $0.0000

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | ok | 0.4 |  |
| 1 | integrity | not_run | 0.0 | not implemented in M0 (M1: verifier 2.x) |
| 2 | build | ok | 0.1 |  |
| 3 | tests | ok | 0.3 |  |
| 4 | traceability | not_run | 0.0 | not implemented in M0 (M1: verifier 1.9) |
| 9 | judge | ok | 51.9 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | PASS |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261004T1647Z-5d0e/012-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261004T1647Z-5d0e/013-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261004T1647Z-5d0e/014-test.log |

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-6e0424fb | money-format › Format an amount with its currency › Two decimals are always shown | pass | pass | the judge passed it |
| C-533d8ece | money-format › Format an amount with its currency › Half a cent rounds up | pass | pass | the judge passed it |
| C-27c6994f | money-format › Format an amount with its currency › Negative amounts keep their sign | pass | pass | the judge passed it |
| C-a71b85f4 | money-format › Format an amount with its currency › Lowercase currency code | pass | pass | the judge passed it |

## Findings

- [minor, judge] Spec gap: currency edge cases not pinned (spec gap): The spec requires ValueError if code is not three uppercase ASCII letters, but does not pin behavior for non-string, empty string, length 2/4, or non-ASCII. Implementation returns ValueError in those cases (isinstance check + length + range). No scenario covers them; reasonable implementations could differ.
- [minor, judge] Spec gap: amount type not pinned (spec gap): Spec shows Decimal in scenarios but does not specify accepted input types. Implementation does Decimal(amount) (constructor). Behavior for non-convertible types, int/float precision semantics, or other numeric types is not covered by any scenario.

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_money::test_format_money_always_shows_two_decimals` (task 1.1): passed
- `tests.test_money::test_format_money_keeps_negative_sign` (task 1.1): passed
- `tests.test_money::test_format_money_rejects_lowercase_currency_code` (task 1.1): passed
- `tests.test_money::test_format_money_rounds_half_a_cent_up` (task 1.1): passed
