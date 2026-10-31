## 1. A passing repair is held as a proposal (D2, D3, D5)

- [ ] 1.1 Write the tests first (tests/unit/implementer/test_repair_step.py, over the real bench it uses). Then
  implement: `held.Check` gains `"repair"`, `held_patch.CHECKS["single"] = ("tests", "repair")`, `_LABEL["repair"]`;
  `held_question` for check `repair` (title, per-test lines, evidence, the accept and person-only lines of D3; the other
  checks byte-identical); `_raise_held` records `repair_blobs` (from `expected_state` of the saved patch: path ->
  `[blob before, blob after]`); `_run_repair`: an agent step that passes every check is captured and held
  (`GreenOutcome("held")`), a replayed step that passes is committed with `task.repaired{..., question,
  patch_sha256}`, a replayed step never holds again; a patch outside the repaired files, with a link, or whose expected
  state is empty, fails the attempt (D3 last paragraph). Cases: SCN-IMP-453, SCN-IMP-471, SCN-IMP-474, SCN-IMP-475,
  SCN-IMP-476, SCN-IMP-477, and the tests of the first design that asserted a commit after an agent step now assert the
  hold (then a replay for the commit).

## 2. Only a person applies it (D4)

- [ ] 2.1 Write the tests first (tests/unit/implementer, tests/unit/delegate, tests/unit/specs/test_questions_cli.py).
  Then implement: `accepted_overrides` counts an accept of check `repair` only with `by: human`; `find_replay` records
  `held.accept_ignored{question, task, check, by}` once for an accept that does not count; `DelegatePass._without_a_call`
  escalates a harness question whose raise has `check: repair`; `l4 questions accept|answer` by an agent refuses it
  whatever `clarifier.answer_by_agents` says (the raise read from the unit's ledger at the folder's head). Cases:
  SCN-IMP-472, SCN-IMP-473; the other harness checks keep their rule (a test each).

## 3. The verifier accepts only the accepted edit (D6)

- [ ] 3.1 Write the tests first (tests/unit/verifier/test_repair_integrity.py). Then implement `_repair_acceptance` in
  `l4.verifier.integrity` and call it from `check_test_paths` for every file a `task.repaired` allows in an exempt
  commit: the five conditions of D6, each failing alone in its own test, and the blocker text. The tests of the first
  design gain the question chain (raise, human answer, replay) so they keep testing what they tested. Cases:
  SCN-VER-278, SCN-VER-280, SCN-VER-281, SCN-VER-282.

## 4. Checks and documents

- [ ] 4.1 docs/SPEC.md: L4-IMP-091, L4-VER-073, the D11 amendment, SCN-IMP-453..477 and SCN-VER-278..282, the events
  (`question.raised.repair_blobs`, `task.repaired` fields, `held.accept_ignored` for `repair`), change-table row 113;
  CHANGELOG (Unreleased); the runbook and the l4 skill's questions page (a repair question is a person's: read the
  diff, then `accept` or `retry`). Then: the implementer, verifier, delegate and specs suites, ruff, the docs tests,
  `openspec validate own-test-repair --strict`.
