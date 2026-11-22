## Context

Read at 0.4.59 (62188257):

- `src/l4/deadline.py:259-279` `COMMITS` (`task.red_committed`, `task.green_committed`, `task.done`), `RESETS`
  (`unit.retried`, `unit.resumed`, `unit.restarted`) and `window(events, task, fix_unit=)`. `stops` and
  `last_is_stop` (L4-IMP-071) read the same window.
- `src/l4/implementer/loop.py:465-495` `seed_attempts`: per phase and profile the `task.attempt_failed` of the window,
  their reasons, the highest attempt number (a `deadline.reached{when: during}` included), and `escalated_from`, the
  `from` of the newest `implementer.escalated` per phase. `_run_task` (619-): `seed_attempts` (626), `resume_red`
  (643), `start` (648), `origin = seeded.escalated_from.get(start)` (653), `_escalate_while_due` before the loop
  (660), the red branch's `red, failure, retry, excerpt = outcome, None, None, ""` after a red commit (708). A blocked
  attempt returns at once and records no `task.attempt_failed`.
- `src/l4/implementer/tdd.py:2186-2216` `run_green`: `_unfreeze_parts` and `_combine`, then on every attempt
  `task.unfrozen` per actor (`reason: human_answer`, `by: human | agent`, `question` the comma-joined ids), per
  delegate grant (`reason: delegate_answer`, one `question`), and for the task's text (`reason: named_by_task`).
  `unfreeze_for(wb, task, manifest)` (2554-2558) gives the same grants without recording anything. `unfreeze.Grant`
  (`src/l4/implementer/unfreeze.py:30-44`) has one `question`, its `reason` and its `paths`.
- `src/l4/delegate/limits.py:121-128` `answers_used` and `limit_reached` (157): the delegate answers at most
  `delegate.max_answers_per_task` questions (default 3) that block a task, over the unit's whole ledger. A person's or
  an agent's answer has no such cap.
- `src/l4/implementer/tdd.py:524-598` `classify_red`: its reasons in order; `regressed` (567-572) are the ids that
  passed in the base report and do not pass now, less stale and named tests; the last reason is `red broke existing
  tests: <ids>` (589-597). `green_failures` (601-631): hang, timeout, no report, collection errors, vacuous, `red
  tests still failing`, then `green broke existing tests: <ids>` (621-626), then `new failing tests added in green`.
  Callers: `run_red` (gate at 1674, `tampered("test run")` at 1675, `classify_red` at 1969-1978), `run_green` (gate at
  2242, `restore_replay(wb, "test run")`, `green_failures` at 2244, `keep_tested` at 2299), `run_single` (gate at 3637,
  `green_failures(base_report, [], gate)` at 3639, `keep_tested` at 3700), `_run_repair` (3481-3484).
- `src/l4/verifier/gate_repeat.py`: `pre_existing` (59-91, the id-to-file rule with the JavaScript and TypeScript
  handling), `tree_reset` (103-145), `_short_of_time` (165-169), `MAX_REPEAT_FAILURES = 5` (40), `_handed_on`
  (279-291). `tdd.py` already imports from `l4.verifier`, and `gate_repeat` imports no implementer step module, so
  there is no cycle.
- `src/l4/deadline.py:133-142` `cap_s`: the agent's limit plus one `gates.timeout` for red, green and single.
- `src/l4/verifier/ladder.py:455-460` `_guards` and 722-726: `VerifyResult.guards` from the ledger.
  `src/l4/verifier/report.py:347-348` lists them, `393-394` stores them in `verdict.json`, and
  `src/l4/verifier/evidence.py:191` restores them for a reused round.

## Goals / Non-Goals

**Goals:** an answer that unfreezes a file for a task's green gives that green a full window, once per answer and
within a stated bound. A step does not fail an attempt on a pre-existing test that passes when run again, and a test
the step broke still fails it. Both are visible in the ledger, and the second also in `verification.md`.

**Non-Goals:** a renewal for red or single, for an answer that unfreezes nothing, or for the deadline's stops; a test
selection inside the consumer's command; the repair chore; a configuration key.

## Decisions

### D1. When a window is renewed (L4-IMP-104)

`_renew_on_answers(wb, task, red, failures, reasons, seeded) -> None` in `loop.py`. It is called at two places, both
before the task's next green attempt in this `_run_task`: after `resume_red` when `start == "green"`, before `origin`
is read and before `_escalate_while_due` (653-660); and right after a red commit of this run (708). It:

1. takes `unfreeze_for(wb, task, red.manifest).grants` with `reason` `human_answer` or `delegate_answer` and at least
   one path. These are the grants that open a frozen file for this green now, under every rule of L4-IMP-015 and
   L4-DLG-014. The `named_by_task` grant is the task's own text, not an answer, and renews nothing;
2. drops each question id that an earlier `task.attempts_renewed` of the task names. The fix unit must match
   (`event_context["fix_unit"]`). The search runs over the whole ledger, not the window, so one answer renews once,
   whatever came between;
3. when ids are left: counts `n`, the green-phase failed attempts in `failures["green"]`. When `n > 0` and the task
   already has `MAX_RENEWALS = 2` renewals with `failed > 0` after the newest `RESETS` event (same fix unit), it logs a
   warning (`task <k>: no attempt renewal for <ids>: 2 renewals since the last retry, resume or restart`) and stops,
   and nothing is recorded. Otherwise it records `task.attempts_renewed{task, phase: "green", questions: [ids],
   failed: n}` and clears `failures["green"]`, `reasons["green"]` and `seeded.escalated_from["green"]`.

A renewal with `failed: 0` is recorded too, so that the answer cannot renew later. It does not count toward the cap.

`seed_attempts` gains one rule: in the window, a `task.attempts_renewed` of the task (same fix unit) with `phase:
"green"` clears `failures["green"]`, `reasons["green"]` and `escalated_from["green"]` gathered so far. `attempts`
(the step numbers) is not cleared, so a step key `<task>/green/<n>` is still used once. `deadline.window`, `COMMITS`
and `RESETS` are not changed. The stop count of L4-IMP-071 and the "first only after a stop" rule read the same window
as before.

After a renewal the phase starts on the run's selected profile with fresh counts, as after `l4 retry` (L4-IMP-094).
The profile that failed against the wrong test is not passed over.

Bound: every renewal needs a question that blocks the task, an answer that a person, an agent acting for one
(`clarifier.answer_by_agents`, L4-QMD-009) or the delegate gave, and a grant that opens a frozen file. Each question
renews at most once per task. At most 2 renewals that clear a failure come between two `l4 retry`, `l4 resume` or
`l4 restart`, whoever answered. The delegate also gives at most `delegate.max_answers_per_task` answers per task. So
between two of those commands a task has at most `3 × implementer.max_task_attempts` failed green attempts: 9 at the
default 3. A question is raised only by a step that ends blocked, which ends the task's turn in the run, so the
renewals of one task cannot follow one another within a run.

Fail-safe: a renewal changes only how many attempts the breaker allows. The grants are those that `run_green` uses
anyway, under the same rules, so nothing more is unfrozen and no person-only action moves to an agent. A ledger that
cannot be read gives no grant, because `unfreeze_for` reads the same files, and so no renewal.

### D2. Which failure gets a re-run (L4-IMP-105)

A new module `src/l4/implementer/recheck.py`. `recheck_candidates(report, regressed, untouched) -> list[str] | None`
gives the ids to re-run, or None when there is no re-run. There is a re-run when all of these hold:

- 1 to `MAX_REPEAT_FAILURES` (5) regressed ids;
- each has status `failed` or `error` in run 1. An id missing from the report is gone, not flaky;
- none holds `TIMEOUT_MARKER` in its message. A hang costs its whole timeout again, and green treats a hang as its
  own reason first (`gate_hung`);
- `untouched(id)` holds for each. That is `gate_repeat`'s id-to-file rule, factored out of `pre_existing` as
  `untouched(tree, changed, red_tests) -> Callable[[str], bool]` (`pre_existing` keeps its behaviour and calls it).
  The tree is `git ls-tree -r --name-only HEAD` plus `wb.changed_files()`, and `changed` is
  `wb.branch_changed_files()` plus `wb.changed_files()`, so a test in a file the unit or this step changed is not
  re-run. The red tests are the step's new ids.

The step must also have failed the attempt for that reason alone:

- red: `classify_red` returns its last reason. `RedVerdict` gains `regressed: tuple[str, ...] = ()`, set only by
  the `red broke existing tests` branch (589-597);
- green and single: `green_failures` returns the `green broke existing tests` reason. It gains a third return value or
  a small result type that says which branch, so that callers do not parse the text.

### D3. The re-run

Before run 1 the step takes `reset = tree_reset(wb.git, wb.worktree, keep=wb.cfg.gates.test.reports)`. This is one
`git ls-files --others --directory`. When the candidates of D2 exist:

1. When `reset` is None or `reset()` is False: no re-run, `stopped: tree`.
2. When `gate_repeat.short_of_time(run1_seconds)` (the private `_short_of_time` made public; run 1's
   `GateResult.seconds`): no re-run, `stopped: budget`.
3. Otherwise `again = wb.run_gate("test-recheck", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports,
   extra_env=<run 1's>)`, then the step's guard after a gate run: `tampered("test re-run")` in red, `stuck = stuck or
   restore_replay(wb, "test re-run")` in green and single. A `DeadlineReached` passes through. Any other exception of
   the gate is the gate's own, as for run 1.
4. Usable: a report was read, it has no collection error, it executed at least one test, and it holds every candidate.
   Not usable: `stopped: unusable`.
5. `flaky` are the candidates that passed in the re-run, `failing` the others, and `new_failures` the ids that passed
   in run 1 and are `failed` or `error` or missing in the re-run. When `failing` and `new_failures` are both empty,
   `stopped: passed`. Otherwise `stopped: failed`.

The step records `task.tests_rechecked{task, phase, attempt, tests, flaky, failing, new_failures, stopped}` whenever
D2 gave candidates. Lists hold at most 20 ids.

With `stopped: passed` the report of run 1 becomes the *merged report*: run 1's cases, each flaky id's case from the
re-run (`_handed_on`'s rule). The step's check runs again on it (`classify_red(...)` with the same arguments, or
`green_failures(...)`), so a later reason, for example `new failing tests added in green`, still applies. Every later
reader of the step's report uses the merged report: red's checks after the verdict, green's `_undiscriminating` and
browser-test match, and `keep_tested`. The next task's baseline may reuse it (L4-IMP-088), and there the flaky test
shows as passed, which keeps it protected as a pre-existing test. A warning names the flaky tests.

In any other case the attempt fails with run 1's reason, followed by `; failed again on a re-run (L4-IMP-105):
<failing and new_failures ids>` for `failed`, `; its re-run was not usable` for `unusable`, and nothing for `tree` and
`budget`. The excerpt is run 1's.

Bound: at most one re-run per attempt, each bounded by `gates.timeout` as every gate run is. It starts only when the
armed soft deadline leaves run 1's duration plus the larger of 60 seconds and a tenth of it. `deadline.cap_s` does not
change: a step that has no room for the re-run fails the attempt as it does today, and the step's `step.timed`
records the longer step, so later estimates grow within the cap.

Fail-safe: a test that the step broke for good fails in both runs and still fails the attempt. A test that passed in
run 1 and fails in the re-run fails it too. A step that made a test fail only sometimes can pass the attempt, and it is
then named in the ledger and in `verification.md`. Step 1 (L4-VER-038, with its own repeat) and step 3 (L4-VER-076)
run every pre-existing test again before the unit can pass. A test in a file the unit or the step changed, a red test,
a hang and a gone test are never re-run.

### D4. What verification lists (L4-VER-082)

`VerifyResult.step_flakes: list[str]` is built from the unit's ledger (its fix units' events included), as `guards`
is (`ladder._guards`). It takes every `task.tests_rechecked` with `stopped: passed`, one line per flaky id: `<id>
(task <k> <phase> attempt <n>)`, with `, fix unit <f>` when the event has a `fix_unit`. At most 20 lines, then
`(+<n> more)`. `report.py` writes `## Pre-existing tests that passed on a task step's re-run (L4-IMP-105)` after
`## Guard events` when there are lines. `verdict.json` stores `step_flakes`, and `restore_round` restores it like
`guards`. It is not a finding and does not change the verdict.

### D5. Upgrade

A 0.4.59 ledger has neither event. `seed_attempts` then folds as before. A unit waiting on an answer when the pin moves
renews on its next run, because no `task.attempts_renewed` names the question yet. A unit whose 0.4.59 run already used
the answer and then halted on `max_task_attempts` needs a person's `l4 retry` or `l4 resume`, which starts a new
window anyway. A 0.4.59 verdict has no `step_flakes`, so nothing is listed. An older harness ignores both events.

## Risks / Trade-offs

- A green that faces a second wrong line after a renewal can raise another question. That is bounded by D1, and it is
  what the evidence asked for.
- The re-run costs one more gate run for an attempt that fails on one to five pre-existing tests. When they really
  broke, the cost buys nothing.
- A test that a step made flaky can pass a step. Steps 1 and 3 run it again, and the listing names it.
