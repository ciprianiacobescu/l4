## Context

`run_red` (`src/l4/implementer/tdd.py`) checks a red step in this order after the agent step and `run_setup`:

1. the `test` gate (`wb.run_gate("test", ...)`), then `tampered("test run")` and the no-report exit;
2. the criteria checks that need no further run (`check_criteria`, `over_cap_text`, the earlier red, the base specs);
3. the pre-satisfied confirmation of passing new tests: `confirm_pre_satisfied` (the zero-value run, Python only),
   then `confirmed_by_base_run` (`test-base-run`, the whole test gate against the unit base code), then
   `_decide_pre_satisfied`, which raises a `pre_satisfied` held check or applies a recorded accept (`_accept`);
4. `classify_red` (the red verdict) and the named-test rules;
5. run (b), `vacuity_check`, for the criteria that are not pre-satisfied, which can hold a `vacuity` check or apply its
   accept;
6. `worse_static_gates(wb, base, "red")`, then `tampered("static gates")`;
7. the already-satisfied finish or the red commit.

The no-new-test path (a step that adds no test, changes no file and reports `already_satisfied`) runs the same
confirmation on existing passing tests and makes no static gate run: nothing changed, so a static gate cannot be worse
than at the step base.

`run_green` runs the `test` gate, `green_failures`, then (no failure yet) `_undiscriminating`, which runs `fails_at_red`
(`test-at-red`) for corrected tests of an unfrozen file and can hold an `at_red` check or apply its accept, and only then
`reason = reason or worse_static_gates(wb, base, "green") or ...`.

`worse_static_gates` runs every `gates.lint` and `gates.typecheck` command (`run_static_gates`) and compares with the
step base's result (`static_baseline`, measured once per commit). It reads the work tree only: the variant runs swap
production files and put them back by sha256 before they return, so the static gates see the same tree before and after
them.

## Goals / Non-Goals

**Goals:** a step that fails a static gate fails before the harness makes a variant run for it, raises a held check for
it or applies a recorded accept to it; the static gates still run once per step with the same baseline rule and
messages.

**Non-Goals:** a change of the static gates' commands, baseline or feedback; a change of the repair chore, the tests
chore or the fix chore; running the static gates in the no-new-test path; merging the static gates' failure with a red
verdict failure into one message.

## Decisions

### D1. Red: once, before the pre-satisfied confirmation, the base run and run (b)

`run_red` gets a local, run-once check:

```python
static: list[RedOutcome | None] = []  # the static gates' outcome, once per step (L4-IMP-096)

def static_gates() -> RedOutcome | None:
    if not static:
        worse = worse_static_gates(wb, base, "red")  # a lint error in a test file would be frozen and deadlock green
        out = tampered("static gates")
        if out is None and worse:
            wb.discard_changes()
            out = RedOutcome("failed", worse)
        static.append(out)
    return static[0]
```

It is called, and a non-None outcome returned, right before each call of the new-tests path that can make a variant
run, and where `worse_static_gates` is called today:

- before `confirm_pre_satisfied`, when the candidates handed to it (the passing criteria that no earlier red and no
  base spec confirmed) are not empty: it may make the zero-value run, and `confirmed_by_base_run` and
  `_decide_pre_satisfied` (a held check, a recorded accept) follow it;
- before `confirmed_by_base_run` (already done by then; listed so that a later edit keeps the order);
- before `vacuity_check` (run (b)), when `open_criteria and zeroed`;
- where `worse_static_gates` is called today (after run (b) and the per-criterion proofs), so a step that made no
  variant run checks them where it does today, after its red verdict.

Once the outcome is known it is not recomputed: the second and third calls return it. A `tampered("static gates")`
result is returned as today. The no-new-test path calls nothing (see Context).

Why before these runs and not right after the test gate: the cheap red checks that today come before the
pre-satisfied confirmation (`check_criteria`, `over_cap_text`) keep coming first, so a step that fails one of them is
told that failure, not the linter's, as today. Why not after `classify_red`: the red verdict needs the pre-satisfied
result (`allowed_passing`), so it cannot move before the confirmation's runs.

### D2. Green: before the test-at-red run

```python
reason, named = green_failures(red.base_report, sorted(red.new_ids), gate, red.superseded)
...
if not reason:
    reason = worse_static_gates(wb, base, "green")  # L4-IMP-096: before the test-at-red run and any at_red accept
    stuck = stuck or restore_replay(wb, "static gates")  # a replayed step is put back to its patch, as red does
if not reason:
    reason, held = _undiscriminating(wb, red, unfreeze, gate.report, task)
...
reason = reason or stuck or restore_replay(wb, "before the green commit")
```

A static gate is a command that may write files, so a replayed step's tree is put back to its saved patch right after
them (`restore_replay(wb, "static gates")`), before `_undiscriminating` runs `fails_at_red`, as red does through
`tampered("static gates")`.

A green step whose test gate failed does not run the static gates (as today, `reason or ...` short-circuits). The
excerpt and the hang excerpt are unchanged.

### D3. What does not change

- `worse_static_gates`, `static_baseline`, `run_static_gates`, `gate.static_baseline_failed` and the static gates'
  failure text.
- The repair chore (`_run_repair`) runs its proof runs before the static gates, and then checks that the files changed
  after the gates are the repaired tests' files alone; moving the static gates before the proof runs would put what a
  linter or type checker writes into that check. The tests chore and the fix chore (`_run_single` paths) already run
  `worse_static_gates` before their discrimination runs (L4-VER-052).
- The questions' text, the ledger events, the prompts and the configuration.

## Risks / Trade-offs

- A red step that made a variant run and fails both a red check (the verdict, a regression, run (b)) and a static gate is
  told the static gate's failure first; it learns the other on its next attempt. One extra attempt in that case, against
  a variant run of up to `gates.timeout` saved and no question raised over a step that cannot be kept.
- A green step whose corrected test no longer discriminates (the test-at-red run would fail it) and that also fails a
  static gate is now told the static gate's failure first; before, it was told that the test does not discriminate. It
  learns the other on its next attempt.
- The static gates now also run for a red step that is then held: the hold is decided after them, so a held step's
  replay runs them again (as every replay runs every check). The cost is one static run per hold.
