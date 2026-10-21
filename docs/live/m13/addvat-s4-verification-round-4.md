# Verification: openspec:add-vat: PASS (round 4)

traceability: 1/4 criteria covered by a discriminating test

- Base: `bb5f34771042df85daf273a0027ac9c0f7430d80`
- Head: `a6f7e241599d6cdcf005e929c82117052ea13623`
- Implementer profiles: codex
- Judge: claude-code (claude-opus-5-5), 1 call(s), prompt sha256 `a9d9811da3ad9c19be8792bd8c30838f77e47178081e382a0ee31f66320bb19b`
- independence: verified (different_vendor): claude-code anthropic (served claude-opus-5-5), codex openai (tool)
- Cost: $0.1901

## Ladder

| Step | Name | Status | Seconds | Note |
|---|---|---|---|---|
| 0 | preconditions | reused | 0.0 | reused (round 3) |
| 1 | integrity | reused | 0.0 | reused (round 3) |
| 2 | build | reused | 0.0 | reused (round 3) |
| 3 | tests | reused | 0.0 | reused (round 3) |
| 4 | traceability | reused | 0.0 | reused (round 3) |
| 4a | audit sampling | not_run | 0.0 | roles.verifier_agent is empty |
| 9 | judge | reused | 0.0 | reused (round 3) |
| 10 | aggregation | ok | 0.0 | PASS |

## Gates

| Gate | Status | Command | Log |
|---|---|---|---|
| setup | pass | `uv sync --frozen` | .l4-out/gates/r-20261005T0007Z-6657/012-setup.log |
| lint | pass | `.venv/bin/ruff check --extend-exclude .l4 .` | .l4-out/gates/r-20261005T0007Z-6657/013-lint.log |
| test | pass | `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml` | .l4-out/gates/r-20261005T0007Z-6657/014-test.log |

## Integrity

| Check | Status | Note |
|---|---|---|
| protected paths | ok | no protected path differs from the base |
| pre-existing tests | ok | 1 test file(s) compared with the base |
| red-green freeze | ok | 3 task(s): red and green compared |
| content scan | ok | no result-manipulating construct in the changed support and runner files |
| suppressions | skipped | no new suppression comment |
| tdd history | ok | 3 task(s); red tests passing at head: step 3 |

## Traceability

| Id | Criterion | State | Tests (status, proof) | Not evidence |
|---|---|---|---|---|
| C-5427d9c3 | vat › VAT by country › Romanian customer, current rate | uncovered | - | - |
| C-3d5b62ab | vat › VAT by country › German customer | uncovered | - | - |
| C-e28fa9b2 | vat › VAT by country › Unsupported country | uncovered | - | - |
| C-04e19140 | vat › VAT by country — regression 1 › VAT ignores any applied discount code | covered | tests.test_vat::test_cart_total_with_vat_uses_discounted_total (passed, red_assertion) | - |

## Human verdicts

- Q-003 accept C-5427d9c3 by human: satisfied. tests/test_vat.py::test_cart_total_with_vat_for_supported_countries[RO-expected_total0] checks a RO cart of 100.00 gives 121.00 and passes; the M1.1 harness wrote it red then green before criterion tags existed, so it carries no l4 mark. The judge passed the criterion.
- Q-004 accept C-3d5b62ab by human: satisfied. tests/test_vat.py::test_cart_total_with_vat_for_supported_countries[DE-expected_total1] checks a DE cart of 100.00 gives 119.00 and passes; the M1.1 harness wrote it red then green before criterion tags existed, so it carries no l4 mark. The judge passed the criterion.
- Q-005 accept C-e28fa9b2 by human: satisfied. tests/test_vat.py::test_cart_total_with_vat_rejects_unsupported_country and test_vat_rate_rejects_unsupported_country check that US raises UnsupportedCountry and pass; the M1.1 harness wrote them red then green before criterion tags existed, so they carry no l4 mark. The judge passed the ...

## Criteria

| Id | Criterion | Judge | Result | Reason |
|---|---|---|---|---|
| C-5427d9c3 | vat › VAT by country › Romanian customer, current rate | pass | pass | accepted by human: satisfied. tests/test_vat.py::test_cart_total_with_vat_for_supported_countries[RO-expected_total0] checks a RO cart of 100.00 gives 121.00 and passes; the M1.1 harness wrote it red then green before criterion tags existed, so it carries no l4 mark. The judge passed the criterion. |
| C-3d5b62ab | vat › VAT by country › German customer | pass | pass | accepted by human: satisfied. tests/test_vat.py::test_cart_total_with_vat_for_supported_countries[DE-expected_total1] checks a DE cart of 100.00 gives 119.00 and passes; the M1.1 harness wrote it red then green before criterion tags existed, so it carries no l4 mark. The judge passed the criterion. |
| C-e28fa9b2 | vat › VAT by country › Unsupported country | pass | pass | accepted by human: satisfied. tests/test_vat.py::test_cart_total_with_vat_rejects_unsupported_country and test_vat_rate_rejects_unsupported_country check that US raises UnsupportedCountry and pass; the M1.1 harness wrote them red then green before criterion tags existed, so they carry no l4 mark. Th... |
| C-04e19140 | vat › VAT by country — regression 1 › VAT ignores any applied discount code | pass | pass | the judge passed it and a discriminating test passes |

## Findings

- [minor, judge] Requirement text still says 'cart subtotal plus VAT' but the code now uses the discounted total (criterion C-04e19140): In openspec/changes/add-vat/specs/vat/spec.md the requirement is unchanged: '`Cart.total_with_vat(country)` SHALL return the cart subtotal plus VAT'. The fix unit adds a scenario (108.90 after a 10% discount), and the code uses self.total(). So the spec now contradicts itself: its own wording conflicts with the regression scenario. The owner's answer in add-vat-fix-1/questions.md Q-001 says the base is Cart.total().
- [minor, judge] VAT is applied to a total that is already rounded to cents (double rounding) (spec gap) (criterion C-04e19140): total() already quantizes to 0.01 with ROUND_HALF_UP, and total_with_vat quantizes again after applying VAT. A second implementation could apply VAT to the unrounded discounted amount and round only once, and for some sub-cent discounted amounts the results differ. Example, assuming PercentOff computes subtotal*(1-p/100): subtotal 0.05 with 10% off gives 0.045, which total() rounds to 0.05. 0.05*1.21 = 0.0605, which rounds to 0.06. Rounding only once gives 0.045*1.21 = 0.05445, which rounds to 0.05. No scenario pins this down.
- [minor, judge] Country code lookup is case-sensitive (spec gap) (criterion C-e28fa9b2): vat_rate looks the raw string up in _VAT_RATES, so 'ro' or ' RO' raises UnsupportedCountry. Discount-code lookup in the same package is case-insensitive (tests.test_discounts::test_discount_registry_lookup_is_case_insensitive). The spec only says ISO 3166-1 alpha-2, so a reasonable implementation could normalise case either way.

## New tests (red then green, `task.red_ok` in the ledger)

- `tests.test_vat::test_cart_total_with_vat_for_supported_countries[DE-expected_total1]` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_for_supported_countries[RO-expected_total0]` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_rejects_unsupported_country` (task 1.2): passed
- `tests.test_vat::test_cart_total_with_vat_uses_discounted_total` (task 1.1): passed
- `tests.test_vat::test_vat_rate_is_defined_for_supported_countries[DE-expected_rate1]` (task 1.1): passed
- `tests.test_vat::test_vat_rate_is_defined_for_supported_countries[RO-expected_rate0]` (task 1.1): passed
- `tests.test_vat::test_vat_rate_rejects_unsupported_country` (task 1.1): passed
