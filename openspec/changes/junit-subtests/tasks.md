## 1. Read subtests into their test (L4-GAT-006)

- [x] 1.1 Tests first in `tests/unit/gates/test_junit_subtests.py` with recorded unittest-xml-reporting fixtures; then
  `_SUBTEST`, `_PY_CLASSNAME` and `_fold` in `l4.gates.junit`.
  Result: 4 of the 7 new tests failed before the change (subtest ids, red ids missing at green, error over failure, a
  passing parent entry after a failing subtest); all 7 and the existing `test_junit*.py` pass (100). The fixtures were
  recorded with unittest-xml-reporting 4.0.0. ruff check and format are clean.
- [x] 1.2 A stored subtest id names its test: `fold_subtest_id` in `l4.gates.junit`, applied where a ledger's test ids are
  read against a report (`green_failures`, `resume_red`, the verifier's `_red_green`, traceability's red, audit and
  extra proofs, the earlier-red check, integrity's superseded and named-by-task tests), so a unit whose red step ran
  before this rule passes green and verification after the upgrade.
  Result: the two new tests (old red ids at green, the verifier's expected tests) failed without the read-site change
  and pass now; 16 tests in `test_junit_subtests.py`. A consumer's real red report (Django runner with
  unittest-xml-reporting) parsed into one id per test, none with a subtest suffix.
- [x] 1.3 Review fixes: of two equal failures the worse kind wins (`_KIND_RANK`), `assertion_failed` carries an
  assertion failure of any subtest and `variant.test_outcome` takes it as a proof, names over 2000 characters are not
  matched, a subtest description is cut at 120 characters in a message, Unicode module names fold, and the remaining
  ledger readers fold stored ids (`red_notes`, the earlier-red check's `discriminating`, `accepted_overrides`).
  Result: the six new tests (the kind tie in both orders, the variant proof, the long name, the Unicode module, the
  label of an unproven record) failed or errored before the fix where they test it; 22 tests pass.
