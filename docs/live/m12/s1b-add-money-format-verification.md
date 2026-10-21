# Verification: openspec:add-money-format: NEEDS_HUMAN (round 1)

traceability: not checked (M0)

- Base: `8b3347d29bb10895cc28afee8686ab9e6ad9e791`
- Head: `29f836fc2bde1d788a2b94422783ff585064d7de`
- Implementer profiles: codex
- Judge: opencode-free, 1 call(s), prompt sha256 `1e532725812316d2dc3fd53bd2a74497eb00dcc5a04f467f906b2a3297a8b0a4`
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
| 9 | judge | ok | 65.0 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | NEEDS_HUMAN |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261004T1643Z-6ee2/012-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261004T1643Z-6ee2/013-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261004T1643Z-6ee2/014-test.log |

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-6e0424fb | money-format › Format an amount with its currency › Two decimals are always shown | pass | pass | the judge passed it |
| C-533d8ece | money-format › Format an amount with its currency › Half a cent rounds up | pass | pass | the judge passed it |
| C-27c6994f | money-format › Format an amount with its currency › Negative amounts keep their sign | pass | pass | the judge passed it |
| C-a71b85f4 | money-format › Format an amount with its currency › Lowercase currency code | pass | pass | the judge passed it |

## Findings

- [major, judge] Non-Decimal amount type not specified (spec gap): Spec states 'format_money(amount, currency)' and examples use Decimal, but no scenario pins down behavior when amount is not a Decimal. Diff shows amount.quantize(...) (src/pricing/money.py:9) which will raise AttributeError for non-Decimal objects; a reasonable alternative is to validate and raise ValueError. This is a spec_gap (input not constrained by scenarios).
- [minor, judge] Currency edge cases not specified (spec gap): Currency validation in diff requires isinstance(currency,str) and fullmatch [A-Z]{3} (src/pricing/money.py:5-7), raising ValueError otherwise. No scenario covers None, empty string, length!=3, non-ASCII, or whitespace-trimmed forms; two reasonable implementations could differ slightly. This is a spec_gap.
- [minor, judge] Rounding/quantize context not fully constrained (spec gap): Spec states ROUND_HALF_UP to 0.01. Diff uses amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP). No scenario pins down behavior for values with more precision or for amounts that are already quantized; implementation is reasonable but not exhaustively specified (spec_gap).

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_money::test_format_money_always_shows_two_decimals` (task 1.1): passed
- `tests.test_money::test_format_money_keeps_negative_sign` (task 1.1): passed
- `tests.test_money::test_format_money_rejects_lowercase_currency_code` (task 1.1): passed
- `tests.test_money::test_format_money_rounds_half_a_cent_up` (task 1.1): passed
