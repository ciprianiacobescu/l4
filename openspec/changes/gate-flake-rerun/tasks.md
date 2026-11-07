## 1. The repeat (D1 to D9)

- [x] 1.1 Write the tests first, in `tests/unit/verifier/test_gate_repeat.py`, against `gate_repeat.settle` with
  scripted `TestGateOutcome`s (a fake `again(name)` that records the names it is called with and returns prepared
  outcomes, a fake `wb` whose `emit` records events; no sandbox) and against `gate_repeat.pre_existing` on a small git
  repository (the `git_environ` fixture, as `test_base_tests.py` builds one):
  - SCN-VER-288: a pre-existing e2e test that fails in run 1 and passes in run 2 gives `ok`, `again` called once with
    `e2e-repeat-1`, one finding `(minor, deterministic, "a pre-existing test is flaky in the e2e gate")` whose detail is
    `<id> (failed in run 1, passed in run 2)` and whose `log` is the first run's, the handed-on report holding run 2's
    case for the test, `gate.status == "flaky"`, `repeats` one `pass` row named `e2e-repeat-1`, and exactly one event
    `verify.gate_repeat{round, gate: "e2e", runs: 2, flaky: [<id>], failing: [], stopped: "passed"}`.
  - SCN-VER-289: a pre-existing test that fails in every run with `runs=3` calls `again` with `e2e-repeat-1` and
    `e2e-repeat-2` and never a third time; the one finding is the blocker `e2e gate failed` (the same `F-` id as the
    first run's) with the detail `` `<command>` failed (3 runs); failing: <id> ``; `stopped: "limit"`; `gate.status`
    stays `fail`.
  - SCN-VER-290: a first run that fails a pre-existing test and a red test of the unit never calls `again`; the outcome
    is the first run's unchanged; no event.
  - SCN-VER-291: `pre_existing` is False for a test whose file a harness commit of `base..head` changed, and for one
    whose file a person's commit changed; `settle` then makes no repeat.
  - SCN-VER-292: `runs=1` makes no repeat.
  - SCN-VER-293: run 1 fails pre-existing A, run 2 passes A and fails pre-existing B (passed in run 1): both flaky,
    `stopped: "passed"`, `ok` after two runs. Run 1 fails A, run 2 passes A and fails a red test N (passed in run 1):
    `stopped: "not_pre_existing"`, the minor finding names A and the blocker `<gate> gate failed` names N only.
  - SCN-VER-294: each unusable repeat (report None, a collection error, a missing `must_contain` id, `executed == 0`,
    status `fail` with every case `passed`) ends the repeats with `stopped: "unusable"` and the blocker naming the
    first run's test; its cases count for nothing. A repeat whose finding is `ALTERED` adds that blocker and stops.
  - SCN-VER-296: no repeat for a first run with a collection error, with `executed == 0`, with the `ALTERED` finding,
    with six failing pre-existing tests (`MAX_REPEAT_FAILURES` is 5; five are repeated), with a failing test whose file
    is not found, or with a missing `must_contain` id.
  - `pre_existing`: True for a pytest id (`tests.test_cart.TestCart::test_total`) and for a TypeScript reporter id
    (`e2e.signin.spec.ts::sign in shows the form`) of a file `base..head` does not change; False for a file the unit
    added, for an id that matches a changed and an unchanged path, for an id with no file, and for a red test id
    (`fold_subtest_id` applied); the tree and the diff are read once, on the first call, and not at all when it is
    never called.

  Then write `src/l4/verifier/gate_repeat.py`:
  - `FLAKY_TITLE = "a pre-existing test is flaky in the {gate} gate"`, `MAX_REPEAT_FAILURES = 5`,
    `repeat_name(gate, n) -> f"{gate}-repeat-{n}"`, `is_repeat(name) -> bool` (`^(test|e2e)-repeat-\d+$`);
  - `pre_existing(git, base_sha, head, red_tests) -> Callable[[str], bool]` (D1): on its first call it reads
    `git ls-tree -r --name-only -z <head>` and `integrity._changed(git, base_sha, head)`; a test is pre-existing when
    `fold_subtest_id(t)` is not in `red_tests`, `test_locate.file_of_id(t, tree, set(changed))` is not None and that
    file is not in `changed`; a `GitError` makes every test not pre-existing;
  - `settle(wb, first, *, gate, command, must_contain, again, is_pre_existing, runs, round_no)`, generic over
    `TestGateOutcome` (an `E2eGateOutcome` comes back as one, through `dataclasses.replace`, its `snapshot` kept): the
    first run's eligibility (D2), the loop (D3), the rule over runs (D4), the findings (D5), the handed-on report (D6),
    the event, `repeats` and `repeat_note` (D7: `<gate>: <runs> runs (L4-VER-076); flaky: <ids>; still failing: <ids>`,
    each list the first five, an empty part left out). It returns `first` itself when it makes no repeat.

- [x] 1.2 `src/l4/verifier/gates.py`: `run_test_gate(wb, must_contain, *, extra_env=None, name="test")` and
  `run_e2e_gate(wb, *, name="e2e")` pass `name` to `wb.run_gate` and `run_e2e`; `TestGateOutcome` gains
  `repeats: list[GateLine]` and `repeat_note: str` (empty by default); `TestGateOutcome.ok` is
  `not any(f.blocking for f in self.findings)`. `src/l4/verifier/types.py`: `GateLine.status` is
  `Literal["pass", "fail", "flaky"]`. The docstrings that call `flaky_repeats` future work (`gates.py:9`,
  `generate.py:14`) say what is built. Existing tests: `test_gates.py`, `test_gates_e2e.py` still pass unchanged.

- [x] 1.3 `ladder.verify_unit.tests` (`ladder.py:720-743`): build `is_pre_existing = gate_repeat.pre_existing(wb.git,
  base_sha, head, set(result.red_green))` once; after `run_test_gate`, `out = settle(wb, out, gate="test",
  command=wb.cfg.gates.test.command, must_contain=set(result.red_green), again=lambda name: run_test_gate(wb,
  set(result.red_green), name=name), …, runs=wb.cfg.verifier.flaky_repeats, round_no=vc.round)` (the repeat gets no
  `extra_env`); `result.gates` takes `out.gate` and then `out.repeats`; the e2e gate runs when the settled `out.ok`,
  and is settled the same way with `again=lambda name: run_e2e_gate(wb, name=name)` and no `must_contain`; `run.e2e`,
  `run.report`, `result.tests`, `result.e2e_tests`, `failure_records` and `_collect_step` read the settled outcomes; the
  step note takes each gate's `repeat_note` in place of its minor finding's detail (blocker details stay in the note
  as today). The first call keeps its shape `run_test_gate(wb, must_contain, extra_env=extra)`,
  so the spy of `test_ladder_evidence_more.py::test_step3_hands_the_gate_the_coverage_env_unless_diff_coverage_is_off`
  still sees one call. Tests, in `tests/unit/verifier/test_gate_repeat_ladder.py`:
  - SCN-VER-288 through the ladder: `run_multi` (`test_ladder_evidence.py:98`) with `gates.e2e.command` set and
    `ladder.run_e2e_gate` replaced by a script keyed on `name` (as that spy replaces `ladder.run_test_gate`), the first
    run failing a test of a file the base already has and `e2e-repeat-1` passing it: step 3 is `ok`, the ledger has
    one `verify.gate_repeat`, `verdict.json` has the rows `e2e` `flaky` and `e2e-repeat-1` `pass`, `tests` holds the
    test `passed` and `failures` does not hold it, `verification.md` shows the two rows, the step note and the minor
    finding, and no fix unit is spawned.
  - SCN-VER-295: the test gate's repeat is called without `extra_env` (so no `L4_COV_RC` and no `-p l4_cov`), the e2e
    gate runs after a test gate that ended ok through a repeat, and the evidence's coverage is the first run's.
  - On a real bench (`make_bench` and `_web_helpers.e2e_config`, as `test_gates_e2e.py`): `run_e2e_gate(wb,
    name="e2e-repeat-1")` serves again, its `gate.finished` and log carry that name, and its finding (if any) is not
    used by `settle`; SCN-VER-297: a repeat whose server never gets ready raises `L4Exit` with
    `ExitCode.INTERNAL_ERROR` out of `settle` (the first run's server came up).

- [x] 1.4 `fixloop.failure_set` (`fixloop.py:498-526`): a row whose name `gate_repeat.is_repeat` matches adds nothing.
  Test in `tests/unit/verifier/test_fixloop.py`: the set of a FAIL round with the rows `e2e fail`, `e2e-repeat-1 fail`
  and `e2e-repeat-2 fail` equals the set with the `e2e` row alone, and a `flaky` row adds nothing.

## 2. Documents and checks

- [x] 2.1 The spec commit has SPEC.md (L4-VER-076; the step-3 row of L4-VER-002; the examples of L4-VER-003; the §3.2
  comment of `flaky_repeats`; `verify.gate_repeat` in §12.1; SCN-VER-05 and SCN-VER-44 amended; SCN-VER-288..297; row
  121) and the CHANGELOG bullet. Check each against the code as built (the names, the event's fields, the finding's
  wording, the note) and correct the text where the code had to differ.
- [x] 2.2 `docs/eval-framework.md`: lines 124 and 186 say `flaky_repeats` is ignored or planned; say that step 3
  repeats a gate whose only failures are pre-existing tests and never repeats new tests.
- [x] 2.3 The verifier suite (`tests/unit/verifier`), the docs tests (`tests/unit/docs`),
  `python scripts/check_spec.py docs/SPEC.md`, ruff, `openspec validate gate-flake-rerun --strict`.
