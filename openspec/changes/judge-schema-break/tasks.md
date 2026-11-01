## 1. The fold (D1)

- [x] 1.1 Write the tests first (tests/unit/verifier/test_judge_repair.py): SCN-VER-283 at the `repair_reply` level and
  through `run_judge` (one call, `reply == "repaired"`), SCN-VER-284 (one string; four items with an object), a fold of
  exactly N + 1 items, and a reply whose only other break is unrelated to the list still repaired or refused as today.
  Then implement `FOLDED_LISTS` and the fold in `judge_repair._walk`, and the module docstring's list of repairs.
  Result: `FOLDED_LISTS` and the fold in `_walk` (a `maxItems` that is a bool is not a limit); six tests in
  test_judge_repair.py (SCN-VER-283 at the function and `run_judge` levels, N + 1 items, SCN-VER-284 both shapes and its
  repair prompt, a fold with an over-long quote). The fold tests failed before the change; SCN-VER-284 passed before
  and after (the reply was already left alone). test_judge_repair 21, test_judge_run 21, test_agent_judge 14,
  test_ladder 26 passed.

## 2. The next judge after a schema break (D2, D3, D4)

- [x] 2.1 Write the tests first: SCN-VER-285 and SCN-VER-286 in tests/unit/verifier/test_judge_chain.py (`run_chain`),
  SCN-VER-287 and the batch case in tests/unit/verifier/test_judge_length_split.py (the batch test that asserted the
  next judge is not asked now asserts that it is asked with the whole prompt; a timeout still holds the round), and a
  follow-up whose reply breaks the schema twice does not call `next_judge`. Then implement D2 in `ladder._ask_judges`.
  Result: `_ask_judges` asks `next_judge("schema_invalid", None)` for a schema break of a prompt that is not a
  follow-up and keeps the discarded result on `WaitingCapacity`; docstrings of `_ask_judges` and `_ask_batches`.
  Tests: SCN-VER-285 (no cool-down, PASS) and SCN-VER-286 (`["free"]` and `["same", "free"]`) in test_judge_chain.py,
  SCN-VER-287 and the batch case (next judge with the whole prompt; with none left the round holds) in
  test_judge_length_split.py, and a follow-up's schema break in test_judge_step_followup.py. The part and batch tests
  failed before the change; SCN-VER-286 guards the hold (it held before too). tests/unit/verifier: 1946 passed,
  3 skipped, 1 xfailed with both changes.

## 3. Checks

- [x] 3.1 SPEC.md (L4-VER-074, L4-VER-075, the W-D1 paragraph, L4-VER-015's timeout row, L4-VER-071's batch sentence,
  SCN-VER-166, SCN-VER-283..287, row 114), CHANGELOG, the verifier suite, ruff,
  `openspec validate judge-schema-break --strict`.
  Result: L4-VER-074, L4-VER-075, the W-D1 paragraph, L4-VER-015's timeout row, L4-VER-071's batch sentence,
  SCN-VER-166, SCN-VER-283..287, row 114 and CHANGELOG Unreleased; tests/unit/docs 120 passed, release notes 9,
  release script 12, template lock 6, `scripts/check_spec.py` clean, ruff check clean, the changed files formatted.
