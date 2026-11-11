## 1. Red: the static gates before the first variant run (D1)

- [ ] 1.1 Write the tests first in a new `tests/unit/implementer/test_static_gates_first.py`, with the fixtures of
  `tests/unit/implementer/conftest.py` (`make_bench`, `red_step`, `green_step`, `result`) and the pattern of
  `test_tdd_static.py` and `test_presatisfied_other_language.py`:
  - SCN-IMP-521: a red step whose new tests pass at head and go to the base run (monkeypatch `confirm_pre_satisfied`
    in `l4.implementer.tdd` to leave them inconclusive, as `test_presatisfied_other_language.py` does), with a
    typecheck command that fails only on the step's change (`sh -c 'if grep -q TYPEBAD <file>; then echo TS2698;
    exit 1; fi'`): the attempt is `failed` with the typecheck text; `confirmed_by_base_run` is not called (monkeypatch
    it to record calls) and no `gate.finished` named `test-base-run` is in the ledger; no `question.raised`, nothing
    held.
  - SCN-IMP-522: a held `pre_satisfied` check answered `accept` (build it as `test_held_accept.py` does), whose
    replayed step fails a lint command: `failed` with the lint text, `confirm_pre_satisfied` and
    `confirmed_by_base_run` not called, and no `check.accepted` and no `criterion.pre_satisfied` events.
  - SCN-IMP-523: a red step with a stub whose new tests fail by assertion (so run (b) would run) and a failing lint
    command: `failed` with the lint text, `vacuity_check` not called.
  - SCN-IMP-524: (a) a red step with no stub whose tests fail by assertion and a lint failure, and a second step that
    also breaks a pre-existing test: the second is told `red broke pre-existing tests` (the verdict comes first when
    no variant run is made); (b) a red step whose passing new tests are confirmed by a (monkeypatched) base run and
    whose static gates pass: `ok`, and the ledger holds exactly one `gate.finished` per lint and typecheck command
    (names `lint`, `typecheck`, not counting `-baseline`).
  Run them and see them fail (SCN-IMP-524 (a) may pass already: it pins the unchanged order).
- [ ] 1.2 Then change `run_red` in `src/l4/implementer/tdd.py` as design D1 says: the run-once local `static_gates()`
  (the `worse_static_gates` call, `tampered("static gates")`, `wb.discard_changes()` and `RedOutcome("failed",
  worse)` of today), called before `confirm_pre_satisfied` when its candidates are not empty, before
  `confirmed_by_base_run`, before `vacuity_check`, and at today's place, which then uses the stored outcome. The
  no-new-test path calls nothing. Keep the comment `# a lint error in a test file would be frozen and deadlock green`.
  Run `uv run --frozen pytest tests/unit/implementer/test_static_gates_first.py tests/unit/implementer/test_tdd_static.py
  tests/unit/implementer/test_tdd_red.py tests/unit/implementer/test_held_accept.py tests/unit/implementer/test_held_check.py
  tests/unit/implementer/test_base_run.py tests/unit/implementer/test_presatisfied_other_language.py -q`.

## 2. Green: the static gates before the test-at-red run (D2)

- [ ] 2.1 Write the test first in `test_static_gates_first.py` (SCN-IMP-525): a green step after an unfreeze (build it
  as `test_tdd_green.py` builds a green step whose corrected tests go to `fails_at_red`), whose typecheck fails on its
  change: `failed` with the typecheck text, `fails_at_red` not called (monkeypatch `l4.implementer.tdd.fails_at_red`
  to record calls), no `gate.finished` named `test-at-red`, no `at_red` hold and no `check.accepted`. Run it and see it
  fail.
- [ ] 2.2 Then change `run_green` as design D2 says, removing `worse_static_gates` from the later `reason = reason or
  ...` line. Run the tests of 1.2 plus `tests/unit/implementer/test_tdd_green.py tests/unit/implementer/test_restore_links.py
  tests/unit/implementer/test_baseline_reuse.py -q`.

## 3. Documents

- [ ] 3.1 `docs/SPEC.md`: in L4-IMP-002, add to check 6 of red "It runs once per step, before the step's first variant
  run when it makes one (L4-IMP-096)." and to item (c) of green "(when (b) gave no failure, before the test-at-red run of
  corrected tests, L4-IMP-096)"; add L4-IMP-096 after L4-IMP-095 with the text of `specs/static-gates-first/spec.md`;
  add SCN-IMP-521..525 after SCN-IMP-520 in the scenario section, in the form of the scenarios around them; add row
  126 `static-gates-first` to the change table of section 21 (what changed, the functions, the consumer case in
  neutral words, the limits: a step that made a variant run and fails both a red check and a static gate is told the
  static gate first; the repair chore keeps its order; requirement and scenario ids; `openspec/changes/static-gates-first/`;
  the test file `test_static_gates_first`).
- [ ] 3.2 `CHANGELOG.md`: under `## Unreleased`, one entry in the style of the 0.4.56 entries: the static gates of a red
  or green step run before its variant runs, so a lint or type error fails the attempt before a base run or a
  zero-value run, and before a held check is raised or an accept applied (L4-IMP-096).
- [ ] 3.3 Run `uv run --frozen python scripts/check_spec.py`, `uv run --frozen pytest tests/unit/docs -q`,
  `uv run --frozen ruff check src tests` and `uv run --frozen ruff format --check src tests`.
