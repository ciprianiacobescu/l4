## Context

Step 3 (`ladder.verify_unit.tests`, `src/l4/verifier/ladder.py:720-743`) runs the unit's test gate once
(`gates.run_test_gate`, `src/l4/verifier/gates.py:227-235`: `wb.run_gate("test", …)` with the coverage environment of
`_coverage_env` and `must_contain` = the unit's red tests). Only when that gate is ok (`ladder.py:731`) does it run the
e2e gate once (`gates.run_e2e_gate`, `gates.py:249-254` → `l4.gates.e2e.run_e2e`, `src/l4/gates/e2e.py:127-166`). The
e2e gate is one gate spawn of the launcher (`launcher_command`, `e2e.py:98-106`; `src/l4/gates/e2e_launch.py`) that
starts `gates.e2e.serve.command`, polls `serve.ready_url`, saves the page snapshot, runs `gates.e2e.command` and tears
the server down: nothing is up after the gate. `run_e2e` clears the snapshot and the not-ready marker before each run,
and a server that never gets ready raises `ServerNotReady` (exit 1, not a finding). Each gate run removes its report
files before the command (`gates.runner.run_gate`) and emits `gate.finished{name, status, …}`
(`src/l4/implementer/workbench.py:546-552`); the soft deadline raises `DeadlineReached` after it (`workbench.py:553`).
`_judged` (`gates.py:147-169`) turns a failed run into one blocker `<gate> gate failed` whose detail names up to five
failing ids; any failing test fails the step and the round.

`verifier.flaky_repeats` (`src/l4/config/schema.py:707`, default 3, at least 1) is read nowhere. The one repeat in
the verifier is step 1's (`base_tests.check_base_tests`, `src/l4/verifier/base_tests.py:297-332`): with the unit's test
and support files at the base, the test gate runs again (`base-tests-repeat`) when anything failed, and a base-passing
test that passes on the repeat is the minor `FLAKY_TITLE` (`base_tests.py:55`). Step 1 runs only when the unit changed a
test or support file.

`gates.test.targeted` (`schema.py:216`) is a bare string that no code reads.

## Goals / Non-Goals

**Goals:** a pre-existing test that fails once at head and passes when the same gate runs again no longer fails the
round or spawns a fix unit; it is a minor finding. A real failure still fails the round. The cost is bounded by
`flaky_repeats` and is one extra gate run in the common case.

**Non-Goals:** repeating new tests or passing tests (the SPEC's "each new test repeated `flaky_repeats` times" is not
built and is removed); a targeted run of single test ids; a change to step 1's repeat, to the implementer's gates, to
the fix chores or to the rule that a fix chore which changed nothing is not done (SPEC 0.4.45 paragraph, L4-IMP-090;
L4-FBK-005's retake is the only chore that completes without a change). That rule fails a no-op chore on purpose; with
this change a flake no longer spawns a fix unit, so the chore never runs for it.

## Decisions

### D1. A failing test is a candidate only when it is pre-existing

A failing (`failed` or `error`) test id `t` of a run is *pre-existing* when all three hold:

1. `fold_subtest_id(t)` is not a red test of the unit (`VerifyResult.red_green`, from `task.red_ok`);
2. `test_locate.file_of_id(t, tree, changed)` finds its file, where `tree` is `git ls-tree -r --name-only -z <head>`
   and `changed` the paths of `git diff --name-status -z --no-renames <base> <head>` (`integrity._changed`), the
   lookup `carryover.decide` already uses (`src/l4/verifier/carryover.py:233-241`); preferring a changed path when
   several match is the cautious side;
3. that file is not a key of `changed`: it is at the base with the content it has at head.

A test whose file is not found is not pre-existing (fail closed, as L4-VER-038's "a test with no file has none of the
allowances"); a Go id `<import path>::<name>` is not mapped by `file_of_id` and so is never repeated. Every commit of
`base..head` counts, a person's included: a test in a file a person changed on the unit branch is not repeated. The
raw diff is used, not `support_base.unit_test_plan`, which keeps only `tdd.test_globs` and `test_support_globs`: an
e2e directory outside those globs would otherwise read as unchanged. A support file the unit changed (a page object, a
fixture) does not stop the repeat; a test it breaks fails every run and stays a blocker.

*Alternative rejected:* require the test to have passed at the base. Step 3 has no base report (step 1's R0 exists only
when the unit changed a test or support file), and a merge-base run would cost more than the repeat it decides.

### D2. When a gate is repeated

After the first run of a gate (`test`, then `e2e`), the gate is run again only when:

- the run failed, its report was read (`report is not None`: not a timeout, a missing or unreadable report, or a link),
  the report holds no collection error and at least one `failed` or `error` test;
- every id of the run's `must_contain` is in the report (the test gate's new tests ran);
- the run's finding is not `the test report was altered` (`gates.ALTERED`);
- at most `MAX_REPEAT_FAILURES = 5` tests failed or errored: a flake is one or a few tests, and a change that breaks the
  app fails many; repeating those would run a slow suite three times for a certain blocker;
- every failing test is pre-existing (D1);
- `verifier.flaky_repeats` > 1.

A vacuous run (`0 tests executed`) and a run whose exit code failed with no failing test are excluded by the first
point. Under any other condition the gate is judged as today, with no repeat and no new event.

### D3. How many runs, and when they stop

A gate runs at most `verifier.flaky_repeats` times in all, its first run included: the default 3 allows two repeats,
and `flaky_repeats: 1` none. The repeats stop early, after the run in which the last candidate that had not yet passed
passes. So a flake costs one more gate run (two when it fails again on the first repeat), and a pre-existing test that
fails on every run costs two more before its blocker. The value keeps the meaning the §3.2 comment gives it (N runs),
and the early stop keeps the common case at one extra run.

Repeat `n` (1, 2, …) is run as the gate named `<gate>-repeat-<n>` (`test-repeat-1`, `e2e-repeat-1`), after the
house name `base-tests-repeat`. A repeat is *usable* when its report was read, holds no collection error and every
`must_contain` id, and either the gate passed or at least one test failed or errored. The loop also stops, before the
limit, after a repeat that is not usable (no report, a timeout, a collection error, a missing `must_contain` id, `0
tests executed`, an exit code that failed with every test passing) or that fails a test that is not pre-existing. The
cases of an unusable repeat count for nothing. A repeat whose report is altered adds the `the test report was altered`
blocker, as the first run would, and stops.

### D4. One rule over all runs

Over every run of the gate that gave a usable report (an id absent from a run's report did not pass in it):

- a test that failed in one run and passed in another is **flaky**: whichever run failed, the first or a repeat;
- a pre-existing test that failed and never passed **still fails**;
- a test that is not pre-existing and failed in any run **still fails**, even when it passed in the first run (a test
  of the unit that flips is not trusted).

Flaky tests are one minor finding per gate; the tests that still fail keep the gate's blocker. A test that fails only in
a repeat, after it passed in the first run, is therefore flaky when it is pre-existing and a blocker when it is the
unit's: no special case. The gate is ok when nothing still fails, even when no single run passed as a whole (two
pre-existing tests that each failed in a different run are both flaky).

### D5. The finding

`gate_repeat.FLAKY_TITLE = "a pre-existing test is flaky in the {gate} gate"`: severity `minor`, source
`deterministic`, the gate's first-run log, detail the flaky ids each with the runs it failed and passed in
(`e2e/test_signin.py::test_form (failed in run 1, passed in run 2)`), listed as `integrity._listed` lists (five, then
`(+n more)`). Minor findings never block (L4-VER-003); one with no criterion and no scenario never becomes a fix task
(`fixunit`, "a minor finding with no criterion and no scenario"), so a flake spawns no fix unit even under
`verifier.fix_minor_findings`.

*Alternative rejected:* reuse `base_tests.FLAKY_TITLE`. A finding's id is the hash of its title and criterion
(`types.finding_id`); step 1 can raise that title in the same round for its own run, and two findings with one `F-` id
would make a person's answer about one of them ambiguous. The new title names the gate, as `e2e gate failed` does.

When tests still fail after repeats, the gate keeps the blocker `<gate> gate failed` (same title and so the same id, the
first run's log), with the detail `` `<command>` failed (<runs> runs); failing: <ids> `` naming only the tests that
still fail (sorted, the first five). With no repeat the blocker is today's, unchanged.

### D6. The report step 3 hands on

Step 4 marks a criterion `fail` when any of its tracing tests did not pass (`traceability.trace_criteria`,
`src/l4/verifier/traceability.py:248`), and a pre-existing test traces an unchanged criterion as `pass_to_pass`. Handing
on the first run's report would fail such a criterion on the flake that step 3 just excused. So the report that step 3
hands on (`run.report`, `run.e2e.report`, `VerifyResult.tests`, `e2e_tests`, the tests-ran check, the judge's report
section) is the first run's, with each flaky test's case replaced by its case from the first run in which it passed, and each
test that still fails but passed in the first run (a repeat failed it: the unit's own test, SCN-VER-293) replaced by its
first failing case, so that the report agrees with the blocker. Every case in it is one that a run produced. `failure_records` is built from that report, so `failures` (L4-VER-069)
holds only the tests that still fail and a fix chore is never asked for a flaky one. The e2e snapshot is the first
run's (`E2eGateOutcome.snapshot`); `.l4-out/e2e/page.html` on disk is the last run's.

### D7. The record

- **Ledger.** Each run emits its own `gate.finished` (the workbench does). After the last repeat of a gate the verifier
  emits `verify.gate_repeat{round, gate, runs, flaky, failing, stopped}`: `gate` `test` or `e2e`; `runs` the runs made,
  the first included; `flaky` and `failing` sorted ids (D4); `stopped` one of `passed` (every candidate passed once),
  `limit` (`flaky_repeats` reached), `not_pre_existing` (a repeat failed a test that is not pre-existing),
  `unusable` (a repeat gave no usable report, or an altered one). No event when the gate was not repeated.
- **verification.md.** Each repeat is a row of the Gates table (`| e2e-repeat-1 | pass | … |`), with its real status.
  The first run's row reads `flaky` (`GateLine.status` gains the value) when every test that failed in it is flaky and
  nothing still fails; otherwise it stays `fail`. The Ladder row of step 3 names the repeats: `<gate>: <runs> runs
  (L4-VER-076); flaky: <ids>; still failing: <ids>`, each list the first five, an empty part left out. The minor finding
  is listed with the other findings.
- **Readers of `gates`.** `fixloop.failure_set` (same_failure, `src/l4/verifier/fixloop.py:498-526`) skips a row named
  `<test gate>-repeat-<n>`: the failing ids in `tests` already say what still fails, and a round that repeated and one
  that did not then compare alike. A `flaky` row is not `fail`, so neither `failure_set` nor the experience graph
  (`kg/extract.py:377-381`, `GATE_FAILED`) counts it. A repeat row that failed is a `GATE_FAILED` edge of its own name in
  the experience graph; that reader is unchanged.

### D8. How a repeat runs

The whole gate command runs again, not the failing ids: `gates.test.targeted` is read nowhere and has no per-language
form, and turning report ids into selectors (a pytest node id, a Playwright `--grep`, a Vitest name) is the per-language
work this change avoids. The JUnit report the gate already writes is all the loop reads.

- **Test gate.** `run_test_gate(wb, must_contain, name="test-repeat-<n>")`, the same `must_contain`, **without** the
  coverage environment: step 6 reads the first run's coverage (`_coverage_env` wrote its nonce once), and a repeat
  that loaded `l4_cov` would overwrite `coverage.json` and `status.json`.
- **E2e gate.** `run_e2e_gate(wb, name="e2e-repeat-<n>")`: a new launcher spawn serves the app again, waits for
  `ready_url` again and tears it down again; the build of step 2 is still in the worktree. A server that never gets
  ready in a repeat raises `ServerNotReady` as in the first run (exit 1, the round stays `verifying` and is run again):
  it is the runner's trouble, and finishing the round on the first run's failure would spawn the fix unit this change
  avoids.
- **Order.** The test gate's repeats come first; the e2e gate runs when the test gate ends ok after its repeats. Each
  gate has its own `flaky_repeats` runs, so step 3 runs at most `2 × flaky_repeats` gates.
- **Deadline.** A repeat that reaches the soft deadline raises `DeadlineReached` like every gate (L4-IMP-068): the
  round is handed back and step 3 runs again, its repeats included, in the next run.

### D9. Where the code goes

A new module `src/l4/verifier/gate_repeat.py` holds `FLAKY_TITLE`, `MAX_REPEAT_FAILURES`, `repeat_name`,
`is_repeat`, the candidate rule (`pre_existing`) and the loop (`settle`), which takes the first `TestGateOutcome` and a
callable that runs the gate again under a given name, so it is tested without a sandbox. `gates.py` stays the thin
adapter: `run_test_gate` and `run_e2e_gate` take `name`, `TestGateOutcome` gains `repeats: list[GateLine]`, and
`TestGateOutcome.ok` becomes "no blocking finding" (today every finding there is a blocker, so nothing else changes).

## Risks / Trade-offs

- A test that the unit's product change made flaky (a race it introduced) passes on a repeat and becomes a minor
  finding, not a blocker. The finding names it in the PR, and the same trade was made for step 1 (L4-VER-038). A
  deterministic regression of a pre-existing test still fails every run.
- A pre-existing test that fails deterministically now costs two more runs of its gate by default (`gates.timeout`
  each at worst), in every round that fails on it. `MAX_REPEAT_FAILURES` keeps a broken app from running a large suite
  three times; a project can set `flaky_repeats: 2` (one repeat) or `1` (none). In CI the extra runs count against
  `ci.time_budget`; the soft deadline hands the round back as for any gate.
- Each e2e repeat starts the server again, so a server that starts unreliably has more chances to fail a round with
  exit 1.
- A flaky pre-existing test whose file the unit changed, or whose id `file_of_id` cannot map (Go), is not repeated:
  such rounds behave as today.
- New tests are never repeated, so a new test that passes but is flaky is not detected in step 3; the old SPEC promise
  was never built and is withdrawn (SCN-VER-05 and SCN-VER-44 are rewritten in place, the house way of retiring a
  scenario's content).
