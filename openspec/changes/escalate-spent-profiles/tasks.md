## 1. Tests first (L4-IMP-094; profiles `impl`, `impl-b`, `impl-c` of the benches stand for deepseek, glm, claude-sonnet)

- [x] 1.1 `tests/unit/implementer/test_escalate_spent_profiles.py`, at loop level with `make_bench`, a three-profile
  chain (`roles.implementer: [impl, impl-b, impl-c]`, `escalate_after: 2`, `max_task_attempts: 3`, as `THREE` in
  `test_loop.py`), earlier runs' records written with the bench's writer as `test_loop.fail` does, and a new fake hook
  `SelectingHook(chain, cooling=())` that behaves like `_escalation_profile`: it walks after `request.profile` in two
  passes (pass 1 skips a profile in `cooling` and one that `used_constraint(request, 2, 3)` refuses; pass 2, only when
  pass 1 takes nothing and a later profile is in `request.used`, skips a profile in `cooling` and one that
  `spent_constraint(request, 3)` refuses), returns the next profile's workbench, or a reason naming each skipped
  profile when none is left, and records every request and pass (`ChainHook` moves blindly: do not
  reuse it). Tests:
  - `seed_attempts` returns `escalated_from[phase]` = the `from` of the newest `implementer.escalated` of the phase in
    the window; one of another task, of another fix unit, or before a `unit.retried` is not read; a phase with none has
    no key.
  - SCN-IMP-500 (the run-B replay): seeded red failures 1 and 2 on `impl-b` and `implementer.escalated{from: impl-b,
    to: impl-c}`; the bench on `impl`. The first request is `(profile impl-b, attempt 3)`; `implementer.escalated{from:
    impl-b, to: impl-c, failures: 2, attempt: 3}` comes before the first `step.started`; with three failing reds the
    steps are `[("red", "impl-c", 3), ("red", "impl-c", 4), ("red", "impl-c", 5)]`, no step runs on `impl`, and the
    halt reason starts `task 1.1: max_task_attempts (3) reached in red on impl-b (2), impl-c (3); last failure: `.
  - SCN-IMP-501: seeded failures 1 and 2 on `impl-b` and an `implementer.escalation_skipped{from: impl-b}`, no move;
    `impl` fails reds 3 and 4: the one request is `impl@5` (with `used == (("impl-b", 2), ("impl", 2))`, one pass), the
    one move `(impl, impl-c)`, and step 5 runs on `impl-c`. Chain `[impl, impl-b, impl-c]` with `impl-c` cooling and
    `impl-b` at `escalate_after`: pass 2 gives the step to `impl-b` (requests `[impl@5, impl-b@5]`, passes `[1, 2,
    1]`, the ask from `impl-b` refused), it runs step 5 there, and the halt has the clause. `used_constraint` answers
    the `used its share:` text, the `spent:` text for a spent profile, and `None` for any other.
  - SCN-IMP-502: seeded failures 1 to 3 on `impl-b`; `impl` fails twice: the request has `spent == (("impl-b", 3),)`,
    the hook's walk skips it with `spent: 3 failed attempts of red of task 1.1 (implementer.max_task_attempts 3)`, and
    the move is `(impl, impl-c)`.
  - SCN-IMP-503: seeded failures 1 to 3 on `impl-b` and 4 to 6 on `impl-c`; `impl` fails reds 7, 8 and 9: one request
    (after attempt 8; none after 9), one `implementer.escalation_skipped` whose reason names both, no
    `implementer.escalated`, and the reason starts `task 1.1: max_task_attempts (3) reached in red on impl-b (3), impl-c
    (3), impl (3); no later profile can take it (`.
  - SCN-IMP-504: the records of SCN-IMP-500 and `cooling=("impl-c",)`: `implementer.escalation_skipped{from: impl-b,
    on: impl, failures: 2}` before the first step; step 3 runs on `impl`; after `impl`'s failures 3 and 4 the move is
    `(impl, impl-b)`, the move on from `impl-b` is refused (no `on`), step 5 runs on `impl-b`, and its failure halts with
    `… on impl-b (3), impl (2); no later profile can take it (…); last failure: …`.
  - Bounded: every profile seeded with 2 failures and no move: before the first attempt the requests are `[impl,
    impl-b]` (no more than the chain's length) and step 7 runs on `impl-c`; a hook that returns a workbench on the same
    profile ends the loop after one request.
  - SCN-IMP-505 (one run unchanged): nothing seeded, reds failing 2, 2, 3 times: the requests are exactly `[impl@3,
    impl-b@5]` and the halt reason is today's three-profile detail with no clause.
  - SCN-IMP-506: the records of SCN-IMP-500, then `unit.retried`: no request before the first attempt, and the first
    step is `("red", "impl", 1)`.
  - No continuation when F is the bench's profile (the seeded move is from `impl`: one request, as
    `test_seeded_failures_escalate_before_the_first_attempt`), when F comes before it (the bench on `impl-b`, the move
    from `impl`: no request before the first attempt), when F is not in `roles.implementer`, and when `escalate_after`
    is 0.
  - SCN-IMP-507 with `TWO` of `test_escalation.py` and `Hook("impl-b is cooling")`: the reason is `task 1.1:
    max_task_attempts (3) reached in red; no later profile can take it (impl-b is cooling); last failure: …`; with no
    hook, `escalate_after: 0`, or a chain of one profile the reason is today's.
  The existing `test_escalation.py` and `test_loop.py` tests pass unchanged.
- [x] 1.2 `tests/unit/orchestrator/test_escalate_spent_profiles.py`, end to end with `run_l4` and three fake profiles of
  three vendors (`verifier.independence: none`, or judges of a fourth vendor), the earlier run's records seeded with
  `seed_events` of `test_step_deadline.py` after a first run that leaves the branch and ledger: SCN-IMP-500 through the
  real `_escalation_profile` (`availability.selected{selected: impl-c, escalated_from: impl-b}`, the steps' vendors,
  the run's selected profile still `impl`); SCN-IMP-502 (`impl-b`'s entry in `availability.selected.skipped` has step
  `constraint` and the spent reason, and `impl-b` is not probed); SCN-IMP-501 (`impl-b` failed twice: one
  `implementer.escalated` to `impl-c`, one `availability.selected` of the move whose `skipped` lists `impl-b` with the
  `used its share:` reason and no probe, and `impl-b` is not in the fold's `profiles_used`); the pass-2 case (`impl-c`
  cooling, `impl-b` at `escalate_after`: one `availability.selected` of the move, `impl-b` selected and `impl-c` the
  only skipped entry, then the refusal from `impl-b` and the halt clause); SCN-IMP-504 (a cool-down recorded for `impl-c`: no
  `availability.unavailable`, no `waiting_capacity`, the `on` field); SCN-IMP-503 (the `phase.changed` detail of the
  halt holds the clause).
- [x] 1.3 `tests/unit/verifier/test_fixloop_escalate.py`: SCN-IMP-509 (a fix unit's chore with seeded `single`
  failures on `impl-b` and `implementer.escalated{phase: single, fix_unit: …}` continues on `impl-c`, step
  `1.1/single/3`, the run's selected profile unchanged); a seeded move of the unit's own task does not move the fix
  unit's chore.
- [x] 1.4 `tests/unit/obs/test_progress.py`: SCN-IMP-508 (`… it starts on <on>` with `on`; the line without `on` as
  before).

## 2. The rule (D1 to D5)

- [x] 2.1 `l4.implementer.loop.Seeded` gains `escalated_from: dict[str, str]`; `seed_attempts` sets it from the window's
  `implementer.escalated` events of the task and fix unit (newest wins; `phase` in `failures`; `from` a non-empty
  string).
- [x] 2.2 `EscalationRequest` gains `spent` and `used`, both `tuple[tuple[str, int], ...] = ()`; `spent_constraint(
  request, limit)` and `used_constraint(request, limit_after, limit)`, both `-> Constraint` (D1 texts).
  `Orchestrator._escalation_profile` selects in two passes: `constraints=(used_constraint(...), keeper)`, and when that
  raises `RoleUnavailable` and a profile after `request.profile` is in `request.used`, `constraints=(spent_constraint(
  ...), keeper)`; the reason of the last pass is the refusal. The returned `Selected.request` has the constraints of
  pass 2, so a limit on the moved profile (`Factory.on_limit`) never falls back to a spent one (D1).
- [x] 2.3 `_escalate_if_due(..., origin: str | None = None) -> tuple[Workbench, str | None]`: the request's profile and
  count are `origin`'s when given (conditions of L4-IMP-017 for it, `_has_later` on it), `spent` from
  `failures[phase]` (and `used`); a refusal with `origin` different from the workbench's profile records `on` (that profile).
- [x] 2.4 `_escalate_while_due` (D2): the bounded loop of today's `_run_task:475-479`, returning the workbench and the
  newest refusal on the profile it ends on. `_run_task` calls it before the first attempt, after the continuation of D3
  (`origin=seeded.escalated_from.get(start)` when that profile is in `roles.implementer` after the run's profile), and
  after each failed attempt in place of `:551`.
- [x] 2.5 `_run_task`'s halt (D4): the clause `; no later profile can take it (<reason>)` before `; last failure:` when
  `_has_later` holds for the current profile and a refusal on it was recorded; `breaker.tripped` unchanged.
- [x] 2.6 `ProgressLog._escalation_skipped` (D5): `it starts on <on>` when `on` is set.

## 3. Docs and checks

- [x] 3.1 `docs/runbook.md`: the bullet "Failed attempts count across runs" (a later run continues a moved step where it
  went), the escalation NOTE (a move skips a profile with no attempt left and moves on from one that used
  `escalate_after`), the log-line table (the `it starts on <on>` line), the `max_task_attempts` row of the halt table
  (the clause). SPEC.md and CHANGELOG are in the spec commit; correct them if the code differs.
- [x] 3.2 The implementer, orchestrator, verifier and obs suites (`tests/unit/implementer`, `tests/unit/orchestrator`,
  `tests/unit/verifier/test_fixloop_escalate.py`, `tests/unit/obs/test_progress.py`), the docs tests
  (`tests/unit/docs`), `python3 scripts/check_spec.py docs/SPEC.md`, ruff, `openspec validate escalate-spent-profiles
  --strict`. No full suite run on a shared machine.
