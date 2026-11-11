## Why

In a consumer's TypeScript unit, a red step for a task whose text said it adds no green code wrote one new test file.
Its five tests passed at head, so the harness tried to confirm them as pre-satisfied. The zero-value run varies Python
files only, the base run hit the 30-minute gate timeout, the task was held with a `pre_satisfied` harness question, and
the delegate accepted it. The replay ran the test gate (5 minutes), the base run again (30 minutes), recorded the
accept (`check.accepted`, `criterion.pre_satisfied{via: delegate_override}`), and only then ran `gates.typecheck`, which
failed in 9 seconds on a type error in the new test file. The attempt failed, the accept was spent on a step that could
never be kept, and the next attempt raised the same question again.

The cause is the order of the red checks. `run_red` runs the static gates (`worse_static_gates`, check 6 of
L4-IMP-002) last: after the pre-satisfied confirmation (the zero-value run, `test-base-run`), after run (b) (the vacuity
check) and after a held check has been raised or its recorded accept applied. Green has the same shape: `run_green`
runs the test-at-red run of corrected tests (`_undiscriminating`, `fails_at_red`) and applies an `at_red` accept before
`worse_static_gates`. A static gate needs no variant run and no person, and it is the cheapest check of the step.

## What Changes

- Red: the static gates run once per step, before the step's first variant run (the pre-satisfied confirmation's
  zero-value run and base run, run (b)); a step that makes no variant run keeps today's order. A static gate that
  passed at the step base and fails now fails the attempt before any variant run is made, before a held check is
  raised and before a recorded accept is applied, with today's message and feedback.
- Green: when the test gate gives no failure, the static gates run before the test-at-red run of corrected tests and
  before an `at_red` accept is applied; a failing static gate fails the attempt as today.
- The static gates still run exactly once per step; their baseline rule (`gate.static_baseline_failed`) is unchanged.
- The repair chore (L4-IMP-091), the tests chore and the fix chore keep their order: the repair chore checks which
  files the gates changed after its proof runs, and the two chores already run the static gates before their
  discrimination runs.

## Capabilities

### New Capabilities

- `static-gates-first`: L4-IMP-096, the static gates of a red or green step come before its variant runs.

### Modified Capabilities

- L4-IMP-002 (check 6 of red, item (c) of green): say where the static gates run.

## Impact

- `src/l4/implementer/tdd.py` (`run_red`, `run_green`).
- `docs/SPEC.md` (L4-IMP-002, the new L4-IMP-096, SCN-IMP-521..525, change-table row 126), `CHANGELOG.md`.
- No change of configuration, prompts, ledger events or the questions' text. A red step that fails both a red check
  and a static gate may now be told the static gate's failure first when it made a variant run; it is told the other
  on its next attempt.
