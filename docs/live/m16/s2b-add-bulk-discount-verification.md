# Verification: openspec:add-bulk-discount: NEEDS_HUMAN (round 1)

traceability: 2/2 criteria covered by a discriminating test

- Base: `b98d1d06de9be5f42939fc71c88cd8988e4b5046`
- Head: `790d85b08fa40ab14e138e6daaff4a4bcfae011f`
- Implementer profiles: codex
- Judge: claude-code (claude-opus-5-5), 1 call(s), prompt sha256 `306228b49d66a11843242910c82296359380a98e29e6a8970567a4fe03d1acd8`
- independence: verified (different_vendor): claude-code anthropic (served claude-opus-5-5), codex openai (tool)
- Cost: $0.1372

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | ok | 0.6 | base main@b98d1d06de contained |
| 1 | integrity | ok | 0.1 | 6 sub-checks; scope: 8 changed file(s), 1 held |
| 2 | build | ok | 0.2 |  |
| 3 | tests | ok | 4.6 |  |
| 4 | traceability | ok | 0.0 | 2/2 criteria covered |
| 4a | audit sampling | not_run | 0.0 | verifier.audit_sample_ratio is 0 |
| 5 | ui test generation | not_run | 0.0 | the unit changed no file under verifier.playwright.ui_paths |
| 6 | quality | ok | 0.0 | 7.9% of the changed executable lines ran |
| 8 | s1 judge | ok | 33.0 | 2/2 criteria judged by laya-local |
| 9 | judge | ok | 27.7 | 1 call(s) |
| 10 | aggregation | ok | 0.0 | NEEDS_HUMAN |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261005T0921Z-1804/013-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261005T0921Z-1804/014-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261005T0921Z-1804/015-test.log |
| e2e | pass | `.venv/bin/python -m pytest e2e -p no:cacheprovider --junitxml=.l4-out/e2e-junit.xml --output .l4-out/e2e/artifacts --tracing retain-on-failure --screenshot only-on-failure` | .l4-out/gates/r-20261005T0921Z-1804/016-e2e.log |

## Integrity

| Check | Status | Note |
|---|---|---|
| protected paths | ok | no protected path differs from the base |
| pre-existing tests | ok | 1 test file(s) compared with the base |
| red-green freeze | ok | 1 task(s): red and green compared |
| content scan | ok | no result-manipulating construct in the changed support and runner files |
| suppressions | skipped | no new suppression comment |
| tdd history | ok | 1 task(s); red tests passing at head: step 3 |

## Traceability

| Id | Criterion | State | Tests (status, proof) | Not evidence | S1 p |
|---|---|---|---|---|---|
| C-534a6caa | bulk-discount › Bulk discount › A cart of 10 items gets the bulk discount | covered | tests.test_discounts::test_bulk_discount_threshold_counts_units (passed, zero_value) | - | 0.56 |
| C-5de37e46 | bulk-discount › Bulk discount › A cart of 9 items gets none | covered | tests.test_discounts::test_bulk_discount_threshold_counts_units (passed, zero_value) | - | 0.53 |

## Evidence

### Needs attention

- out of scope: `src/inventory/stock.py` (module `inventory`)
- changed code not run by tests: `src/pricing/receipt.py::<module>` (uncovered)
- changed code not run by tests: `src/pricing/receipt.py::format_line` (uncovered)
- changed code not run by tests: `src/pricing/receipt.py::format_total` (uncovered)
- changed code not run by tests: `src/pricing/receipt.py::format_receipt` (uncovered)

### Files

| Path | Module | Label | Why |
|---|---|---|---|
| `openspec/changes/add-bulk-discount/.l4/ledger/r-20261005T0919Z-b5be.jsonl` |  | none | exempt: harness, spec or documentation path |
| `openspec/changes/add-bulk-discount/.l4/ledger/r-20261005T0921Z-1804.jsonl` |  | none | exempt: harness, spec or documentation path |
| `openspec/changes/add-bulk-discount/questions.md` |  | none | exempt: harness, spec or documentation path |
| `openspec/changes/add-bulk-discount/tasks.md` |  | none | exempt: harness, spec or documentation path |
| `src/inventory/stock.py` | inventory | out_of_scope | module `inventory` is not named in the spec |
| `src/pricing/discounts.py` | pricing | relevant | named in the spec |
| `src/pricing/receipt.py` | pricing | relevant | module `pricing` is named in the spec |
| `tests/test_discounts.py` |  | relevant | named in the spec |

### Changed functions

7.9% of the changed executable lines ran.

| Function | Status | Lines run | Tests |
|---|---|---|---|
| `src/inventory/stock.py::<module>` | covered | 1/1 |  |
| `src/pricing/discounts.py::<module>` | covered | 1/1 |  |
| `src/pricing/discounts.py::bulk_discount` | covered | 3/3 | test_discounts.test_bulk_discount_threshold_counts_units |
| `src/pricing/receipt.py::<module>` | uncovered | 0/5 |  |
| `src/pricing/receipt.py::format_line` | uncovered | 0/17 |  |
| `src/pricing/receipt.py::format_receipt` | uncovered | 0/24 |  |
| `src/pricing/receipt.py::format_total` | uncovered | 0/12 |  |

### Tests

22 of 22 passed, 0 failed, 0 errored, 0 skipped.
1 of 1 new tests passed.

## S1 (recorded for calibration, never decides)

| Criterion | Status | p | Model | Engine | Note |
|---|---|---|---|---|---|
| C-534a6caa | ok | 0.561 | laya-rl-agent | laya-local | evidence cut to fit the budget |
| C-5de37e46 | ok | 0.533 | laya-rl-agent | laya-local | evidence cut to fit the budget |

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-534a6caa | bulk-discount › Bulk discount › A cart of 10 items gets the bulk discount | pass | pass | the judge passed it and a discriminating test passes |
| C-5de37e46 | bulk-discount › Bulk discount › A cart of 9 items gets none | pass | pass | the judge passed it and a discriminating test passes |

## Findings

- [major, judge] Unrelated change to LOW_STOCK_THRESHOLD (5 -> 3): The change lowers the inventory low-stock threshold from 5 to 3 in src/inventory/stock.py. No part of the bulk-discount proposal, design, spec or tasks mentions this. It changes which stock quantities count as low (for example, 3 and 4 are no longer low). The stock tests still pass, which suggests they read the constant rather than pinning the value, so this behaviour change goes undetected.
- [major, judge] Out-of-scope, untested new module src/pricing/receipt.py: A 77-line receipt formatter was added. The spec does not ask for it, and the gate report lists no tests for it. It also leaves out the new bulk discount: the discount line it prints is only subtotal - total.
- [minor, judge] Threshold counts units, but no scenario separates units from lines (spec gap) (criterion C-534a6caa): Q-001 was answered 'units', and the code sums quantities. Both scenarios hold whether the code counts units or lines, so the answered decision is pinned only by the implementer's test, not by the spec. For example, a single line of quantity 10 qualifies under unit counting but not under line counting.
- [minor, judge] Half-cent rounding of the discount is not pinned (spec gap) (criterion C-534a6caa): Both scenarios give an exact cent value. A subtotal such as 25.05 gives a 10 % share of 2.505, and half-up rounding versus banker's rounding would differ there. The code rounds half up.
- [minor, judge] Interaction with an applied discount code is not specified (spec gap) (criterion C-534a6caa): bulk_discount uses cart.subtotal(), so it ignores any discount code applied to the cart. Two reasonable implementations differ here: one bases the bulk discount on the pre-code subtotal, the other on the post-code amount.

## Needs a human

- scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name
- diff coverage: changed code not run by any test: `src/pricing/receipt.py::<module>`, `src/pricing/receipt.py::format_line`, `src/pricing/receipt.py::format_receipt`, `src/pricing/receipt.py::format_total`

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_discounts::test_bulk_discount_threshold_counts_units` (task 1.1): passed
