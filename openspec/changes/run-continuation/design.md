## Context

`proposal.md` describes the three observations from a consumer repository. This change finishes L4-IMP-012 inside a
unit, makes the schedule work when the base branch is not the default branch, and makes `l4 yolo status` name a run
that ended without a record. It is built for 0.4.19 on top of the released 0.4.18 (f9116bad).

Labels: [V] verified in the code at f9116bad; [I] inferred, including every statement about GitHub's own behaviour
that this repository does not test.

One correction of the report's words: the event that ends a run is `run.finished` (`src/l4/state/ledger.py:263-264`,
`finish(exit_code)`), not `run.ended`. An "open run" is a `run.started` of `l4 run` with no `run.finished` of the same
run id (`src/l4/state/status.py:288-307`) [V]. This change keeps that name.

## Goals / Non-goals

Goals: when the job's budget is known, a run is never killed by the CI timeout. A step that cannot finish in time is
not started, or is stopped and handed back without counting as an attempt. Exactly one continuation follows. A step
that never fits halts by name instead of looping. A plan on a base that is not the default branch keeps moving on the
schedule. `l4 yolo status` gives the real next command when a run died without a record.

Non-goals:
- Pushing the WIP snapshot (L4-IMP-011's remote form, state-vcs-locks M2 with fencing). The snapshot stays a local
  ref (`src/l4/vcs/wip.py:1-6`, "never pushed") [V]. The work in progress of a stopped step survives only on the same
  runner, where `reconcile` puts it back (`src/l4/state/reconcile.py:1-10`, `RestoreWip`) [V]. On a GitHub-hosted
  runner it is lost. The check before each step (D3) is the normal path, and the stop (D4) is the backstop.
- Session resume (L4-IMP-010). `RunRequest.resume_session_id` is read by `claude_code.py:137` and set by nobody [V].
- Changing how GitLab dispatches a continuation (`unsupported`, `src/l4/forge/gitlab.py:371-373`) [V].
- A new configuration key. The constants below are named in "Contracts".

## D1. The deadline counts from the job's start (L4-IMP-066)

What the code does today [V]: `job_remaining_s` (`src/l4/orchestrator.py:1696-1715`) computes the total from
`ci.time_budget`, or for `auto` from GitLab's `CI_JOB_TIMEOUT` or GitHub's `L4_JOB_TIMEOUT_MINUTES`. It subtracts
`soft_deadline_margin`, then subtracts the time since `CI_JOB_STARTED_AT` when that is set, else since `began`.
`began` is set by `run_units` when it starts (`:1741-1743`, `waits.began = clock.now()`). GitHub sets no job start
variable [I]. On GitHub, the deadline therefore counts from the start of `run_units`. That is after the checkout, the
setup action, `l4 doctor`, `l4 plan --sweep` and the plan step (which may run a review) (`l4.github-action.yml:39-64`)
[V]. In this repository's templates, those steps use the margin without being counted.

Decision:
- Both GitHub templates (`src/l4/ci/templates/l4.github.yml`, `l4.github-action.yml`) get a first step, before
  `actions/checkout`:
  ```yaml
      - name: job start
        run: echo "L4_JOB_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_ENV"
  ```
  It needs no credential and no input. `$GITHUB_ENV` makes the variable visible to every later step [I: GitHub's
  documented mechanism].
- `job_remaining_s` reads the start from `L4_JOB_STARTED_AT`, then `CI_JOB_STARTED_AT`, then `began`, in that order. A
  value that does not parse is skipped (as `CI_JOB_STARTED_AT` is today, `:1711-1714`). Python 3.11's
  `datetime.fromisoformat` reads the `Z` suffix [V: the project's minimum is 3.11].
- When a budget is known and neither variable is set, `run_units` logs once, at INFO:
  `soft deadline: the job's start is unknown (no L4_JOB_STARTED_AT): counting from this run's start; l4 upgrade adds
  the step that records it`.
- `run.started` records `job_timeout_s` (the total before the margin) and `job_started_at` (ISO UTC, when known),
  through the `LedgerWriter.open` call in `run_unit_in_worktree` (`:1471-1477`, beside `**run_environment(...)`). Status reads them (D9).

A consumer gets the step with `l4 upgrade`, which renders the workflow again. Until then, the deadline behaves as it
does today.

## D2. One run deadline (`src/l4/deadline.py`)

A leaf module (it imports nothing from `l4`), on the model of `l4.cancel` (`src/l4/cancel.py`: process-wide state,
an exception that `except Exception` does not catch) [V].

```python
FLOOR_S = 600                 # the smallest estimate of a step
MAX_STOPS = 2                 # stops of one task and phase in a row before the unit halts (D7)

class DeadlineReached(BaseException):   # like RunCancelled: no `except Exception` turns it into a failure
    when: Literal["before", "during"]
    phase: str                 # red | green | single | verify | clarify
    task: str | None
    attempt: int | None
    during: Literal["agent", "judge", "gate"] | None
    gate: str | None
    left_s: float
    estimate_s: float | None

@dataclass
class RunDeadline:
    at: datetime               # the soft deadline, on the factory clock
    clock: Clock               # `now()`; the run's SystemClock, a FakeClock in tests
    event: threading.Event     # set at `at` by a daemon timer, or by `fire()`
    steps: dict[str, float]    # phase -> the longest step of that phase measured in this run
    started: int = 0           # steps started in this run (any unit)
    def remaining_s(self) -> float
    def fired(self) -> bool                   # event.is_set()
    def fire(self) -> None                    # sets the event (the timer and the tests call it)

def arm(deadline: RunDeadline) -> None        # starts the timer (threading.Timer(remaining_s, fire), daemon)
def disarm() -> None                          # cancels the timer, clears the current deadline
def current() -> RunDeadline | None
def fired() -> bool                           # current() is not None and current().fired()
```

`run_units` (`src/l4/orchestrator.py:1718`) arms it once, after it computes the first `job_remaining_s`, when a budget
is known. It disarms it in a `finally` around the loop. The deadline is armed only inside `l4 run`'s units: the plan
step (`yolo_step`), `l4 verify`, `l4 retry` and every other command never see it. The existing check between units
(`:1746-1765`) reads the same object.

Why a run-wide object rather than an event threaded through every constructor: `ProcRunner` is created in six places
(the five adapters and `run_gate`) [V: `grep "ProcRunner()"`], and the verifier, the fix loop and the clarifier each
build their own `Workbench` or judge. One module read in `ProcRunner._wait` covers every process that a unit's run
starts.

## D3. Before a step: the estimate (L4-IMP-067)

Where [V]: every implementer step goes through `run_task` (`src/l4/implementer/loop.py:266`), which calls `run_single`
(`:294`), `run_red` (`:309`) or `run_green` (`:324`). A fix unit's tasks go through the same `run_task` (`_fix`,
`orchestrator.py:1143`). A verification round starts at `Orchestrator._verify` (`:1096`, `trigger =
verify(self._ctx)`). The check goes in those two places, before the call:

```python
def check_before(phase: str, task: str | None, attempt: int | None, recorded: Sequence[float]) -> None
    # in l4.deadline; a no-op when current() is None
```

- `left = remaining_s()`.
- The first step of the run (`started == 0`) starts whenever `left > 0`. This mirrors "the first unit always starts"
  (`orchestrator.py:1733-1734`), and a run that started nothing could not make progress.
- Otherwise the step starts only when `left >= estimate`.
- `estimate(phase) = min(cap, max(FLOOR_S, steps.get(phase, 0), max(recorded)))`, where:
  - `recorded` is the `seconds` of the unit's last 10 `step.timed` events of that phase, and the `ran_s` of its
    `deadline.reached{when: during}` of that phase (D7), read from the unit's events
    as the workbench folds them (`_ledger_events`, `src/l4/implementer/tdd.py:1668`; the orchestrator's `_events()`
    for a round).
  - When the phase has no measure in this run and none recorded, the longest step of any phase is used instead (this
    run's, then the recorded ones). That is the reported case: a 23.5-minute red, then a green with no history.
  - `cap = RunRequest.timeout_s + duration_seconds(gates.timeout)`, that is 1800 s + 1800 s by default. The agent's
    time limit is the dataclass default (`src/l4/agents/base.py:164`, `timeout_s: int = 1800`), which no
    configuration key sets [V]. `gates.timeout` is `30m` (`src/l4/config/schema.py:248`) [V]. The cap keeps one
    outlier (a step that waited out a cool-down) from blocking every later step.
- When the step does not fit: `raise DeadlineReached(when="before", ...)`. D5 handles it.
- When it fits: `started += 1`. After the step returns or raises (any outcome except `DeadlineReached`), its wall time
  on the factory clock updates `steps[phase]` and is recorded as `step.timed{task, phase, attempt, seconds}` (for a
  verification round: `step.timed{phase: "verify", round, seconds}`).

The reported case, step by step: the job's start is known (D1). At 155 minutes, `left = 180·60 − 20·60 − 155·60 =
300 s`. The green phase has no measure, so the estimate falls back to the red's 1410 s. 300 < 1410, so the green is
not started (SCN-IMP-335).

The clarifier and the plan step get no check before they start: their calls are short, and D4 stops them anyway.

## D4. During a step: the stop (L4-IMP-068)

What exists [V]: `ProcRunner._wait` (`src/l4/agents/proc.py:124-173`) already sends SIGINT to the process group when
`interrupt.is_set()`, then SIGKILL to the group after `INTERRUPT_GRACE_S = 5.0` (`:18`, `:159-166`, `:170`), and
returns `ProcOutcome(interrupted=True)`. Every adapter passes `req.interrupt` and maps `interrupted` to status
`cancelled` (`claude_code.py:219-221`, `codex.py:294`, `opencode.py:296`, `kiro_cli.py:180`, `command.py:117`). No
code ever sets `RunRequest.interrupt` (`base.py:168`, a fresh `Event`) [V: grep]. A gate runs through
`ProcRunner.run` without an interrupt (`src/l4/gates/runner.py:173-175`) [V]. SIGINT and not SIGTERM, as L4-IMP-012
requires: Claude exits 143 mid-turn on SIGTERM [V: SPEC L4-IMP-012].

Changes:
- `ProcRunner._wait` treats `deadline.fired()` like a set `interrupt`: SIGINT, then the 5 s grace, then SIGKILL of the
  group. The outcome is `ProcOutcome(interrupted=True, deadline=True)`. A process started after the deadline fired is
  stopped at once. Adapters need no change: they report `cancelled`.
- `run_gate` copies `outcome.deadline` to `GateResult.deadline` (a new field, default False).
- Three places turn a stopped process into `DeadlineReached(when="during")`. Each one is after the cleanup that
  already runs, so no caller changes:
  1. `agent_step` (`src/l4/implementer/tdd.py:763`): after its `finally` (scratch dropped, protected paths and gate
     configuration reverted, ledger restored, environment checked, `:810-826`) and after `agent.finished` and the
     `budget.cost` events (`:827-846`, so a cost the CLI reported is kept). If `run.status == "cancelled"` and
     `deadline.fired()`, it raises `during="agent"`. The `wip_snapshots` box records `step.finished{status:
     deadline}`, distinct from `cancelled`, which keeps meaning a signal from CI.
  2. `Workbench.run_gate_spec` (`src/l4/implementer/workbench.py:386`): after its `finally` restores and after
     `gate.finished`. If `result.deadline`, it raises `during="gate", gate=<name>`.
  3. `AgentJudge._run` (`src/l4/llm/agent_judge.py:116`, `:129`): if the run is `cancelled` and `deadline.fired()`, it
     raises `during="judge"`. This covers the verifier's CLI judges and verifier agent, and a clarifier on a CLI.
- `DeadlineReached` is a `BaseException`. The verifier ladder has `except Exception` blocks that turn any error of
  a part of a step into a hold or a warning (`src/l4/verifier/ladder.py:672` scope, `:731` evidence, `:785` the S1
  shadow) [V]. A deadline raised as an `Exception` inside one of them, or inside a later block of the same kind, would
  be swallowed there [I]. No `except Exception` lies between `agent_step` and `run_task` [V: grep of the implementer].
  The `BaseException` keeps the rule simple in both places. `run_unit` is the one place that catches it (D5).

What D4 cannot stop [I]: an HTTP model call (an API judge, `l4.llm` backends) and a `git` command. They end by their
own timeouts. The CLI judge's default is 600 s (`agent_judge.py:140`), and a CLI judge is stopped by D4 anyway. The
20-minute default margin is larger than every one of these timeouts. The risk is stated in Risks.

## D5. The hand-back (L4-IMP-069)

`Orchestrator.run_unit` (`src/l4/orchestrator.py:379-401`) catches `DeadlineReached` next to `(RoleUnavailable,
RoleLimit)` (`:398`) and calls `_defer(exc)`. It does not use `_park` (`:696-718`): that path takes the
`required_role_unavailable` edge to `waiting_capacity` with a `retry_after` and a capacity section, which is the wrong
state here.

`_defer(exc) -> ExitCode`:
1. Appends `deadline.reached{when, phase, task, attempt, during, gate, left_s, estimate_s}` (keys that are None are
   left out).
2. Applies D7. When the unit halts, it returns the halt's code.
3. Sets `_exit_reason` to one of (redacted, at most 300 characters):
   - `soft deadline: task <k> <phase> not started (<left> s left, step estimated <est> s); the next run continues it`
   - `soft deadline: task <k> <phase> stopped (<during>[ <gate>]); the next run runs it again`
   - for a verification round, `round <n>` in place of `task <k>`.
4. Changes no phase. Fires no lifecycle edge. Counts no attempt: `run_task`'s `failures` and `task.attempt_failed`
   (`loop.py:342-350`) are skipped, because the exception leaves `run_task` before them.
5. Returns `ExitCode.CONTINUE` (10).

Then the existing `close(exit_code=10, failing=False)` (`:1229-1260`) appends `lock.released` and `run.finished`,
commits the run's ledger file only (`_commit_ledger`, `:1332-1343`: it stages the ledger path alone, so the stopped
step's uncommitted changes are not committed) and pushes the unit branch [V]. `run.finished` gets the new optional
`reason`: `LedgerWriter.finish(exit_code, reason=None)` (`ledger.py:263-264`), set from `_exit_reason` when the code is
10 and the reason starts with `soft deadline:`.

What the next run finds [V]: the worktree is built again from the pushed branch. A red that was committed and pushed
before the deadline (`tdd.py:1450-1456`, `wb.push()` after `task.red_committed`) is found by `resume_red`
(`tdd.py:1475`, `loop.py:285`), so only green runs. A step that was stopped starts over. On the same runner, the WIP
ref puts its work back first (`RestoreWip`).

`run_units`: after a unit whose result is a hand-back (`UnitRunResult.deferred = True`, a new field), no further unit
starts. The units left get `not started: soft deadline (…)`, as today (`:1748-1764`). `CommandResult` gets `deferred:
Sequence[str]`, the ids of the units handed back.

## D6. Exactly one continuation (L4-IMP-070)

Today [V]: `continue_left_units` (`orchestrator.py:1675-1693`) dispatches only when `result.code == CONTINUE`, a unit
was `not started: soft deadline`, `ci.continuation == "dispatch"`, and the run is in CI. Then `_start_next_run`
(`:1651-1667`), the plan's own trigger, can start a second run in the same `l4 run` (`:1634-1635`).
`dispatch_continuation` on GitHub sends nothing when a run is `queued` (`src/l4/forge/github.py:635-643`).

Changes:
- The condition becomes: (a unit was left at the soft deadline, or `result.deferred` is not empty), and the run's code
  is a designed stop (`ExitCode` in `CI_ALLOWED = (10, 11, 12, 13)`, `exitcodes.py:38`), and `ci.continuation ==
  "dispatch"`, and the run is in CI. Before, a run where unit A waited for a person (11) and unit B was left at the
  deadline (10) exited 11 and dispatched nothing, so B waited for the schedule [V: `most_severe` order,
  `exitcodes.py:30`]. The order matters: a hand-back stops every later unit (D5), so the only way to have both is a
  unit that parks first and a unit handed back after it (SCN-IMP-346 is written that way).
- No step started in the run (`deadline.current().started == 0`, which only happens when the time was gone before the
  first step): no dispatch. A WARNING says `continuation: not requested: no step fitted before the soft deadline (<s> s
  left at the first step); raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES or ci.time_budget`. Otherwise every
  continuation would find the same lack of time.
- One dispatch per `l4 run`. When `continue_left_units` returns `dispatched` or `already_queued`, `run_command`
  clears `step.start_next_run` before `_start_next_run`. The continuation runs the plan step too, so nothing is lost.
- The continuation keeps today's guard: once per run, and nothing sent when a run is `queued` on the base. It must not
  add an `in_progress` check: the run that dispatches is itself in progress on the base, and would always find itself.
  The relay of D8 uses a separate check that leaves its own run out.

The order holds [V]: each unit's `close()` pushes inside `run_unit_in_worktree` (`:1518-1526`), and
`continue_left_units` runs after every unit (`:1634`). The ledger and the branch are on origin before the dispatch.

What GitHub does with the dispatched run [I: documented concurrency behaviour]: the job's `concurrency: group: l4,
cancel-in-progress: false` (`l4.github.yml:28-30`) keeps the continuation `pending` until this job ends. A newer run
queued in the same group (a scheduled run, for one) cancels the pending continuation and takes its place. When that
newer run is the default branch's stopped run, D8 relays to the base, so the chain continues.

## D7. A step that never fits halts (L4-IMP-071)

`budgets.max_iterations_per_unit` and `no_progress_iterations` exist in the schema only: nothing reads them [V: grep].
Attempts are counted in memory per `run_task` call (`loop.py:274-282`), so they do not carry across runs [V]. Without a
guard, a step that takes longer than one job (agent, then many gate runs) would be stopped in every run. Each
continuation would start it again and throw away three hours of work.

Rule, in `_defer` for `when == "during"`: count the `deadline.reached{when: during, first: true}` events of the same
`task` and `phase` (for a round: `phase: verify`) in the unit's events after the last `task.red_committed`,
`task.green_committed` or `task.done` of that task (for a round: after the last `verify.step` of an earlier round).
`first` says that the stopped step was the first step of its run (`RunDeadline.started == 1` when it started), so it
had the most time one job can give. The current event counts when it is `first`. When the count reaches `MAX_STOPS`
(2):
- append `breaker.tripped{reason: "deadline_repeated", task, phase, stops: 2}`;
- `return self._halt("deadline_repeated", detail)` (`:1075`), with `detail` =
  `task <k> <phase> was stopped at the soft deadline as the first step of 2 runs in a row (<m> min of <b> min usable):
  it does not fit in one job; raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES (or ci.time_budget), or split the task, then l4 retry
  --unit <U> --reason TEXT`.

A halted current unit stops a delivery plan (L4-YOLO-013), as any halt does. `l4 retry` brings the unit back
(halted → `previous_phase`, `retry.py:1-20`) [V]. A halt with no task (a verification round) is already a case today
(`baseline_failed` has none); the readers of `breaker.tripped` and `halt_task` (`l4 status`'s cause, the sticky
section, `note_binding`) must take `task: null`, which task 4.2 checks.

Why only a stop of the first step counts:
- A step stopped when it was not the first of its run may have started late with an estimate that was too small. On
  the next run it is the first step: after a hand-back, the unit's next step is the same task (`select_next_step`
  picks it again, and `resume_red` keeps a committed red), and a plan lets only its current unit run. As the first
  step it always starts (L4-IMP-067), with the whole job. Counting the late stop would halt a step that fits.
- A step that was not started (`when: before`) never counts: it ran nothing.
- Termination: a step is never deferred when it is the first step of its run. So a step that never fits is the first
  step of some run (at the latest once the units before it in the run's order have no more work), is stopped there,
  is the first step again in the next run, and halts at the second such stop. Each run in between made progress on
  another unit or another step, or it dispatched no continuation (L4-IMP-070).

The stopped step's time also feeds the estimate. `deadline.reached{when: during}` records `ran_s`, the seconds the step
ran before it was stopped (a lower bound of its length). D3's `recorded` reads it as a `step.timed` of that phase, so
the same step is not started late again on a small estimate.

## D8. A run on a stale copy of the workflow relays to the base (L4-IMP-072)

What the code does today [V]:
- `stale_pin_stop` (`src/l4/ci/pin_guard.py:65-73`) returns the warning when `pin_check` finds a mismatch. That is only
  in GitHub Actions with `harness.delivery: action` (`:44-62`; it skips outside `GITHUB_ACTIONS` and for another
  delivery). `l4 plan --sweep` (`src/l4/planner.py:423`) and `l4 run` (`src/l4/orchestrator.py:1550-1552`) print it and
  exit 0.
- A scheduled run is on the default branch, so `github.ref_name != L4_BASE_BRANCH` and the `base checkout` step
  detaches to `origin/<base>` (`l4.github-action.yml:46-54`). The checked-out tree is the base. The running harness
  is the default branch's pin, and `pin_check` compares it with the base's copy. That is the mismatch the consumer
  saw.
- With `vendored` delivery, `.l4/bin/l4` comes from the checked-out tree, which is the base's, so there is no
  mismatch. `fetched` reads its commit from the base's config [I]. Only `action` delivery has the problem.
- Both templates grant `actions: write` (`l4.github.yml:21`, `l4.github-action.yml:23`). `dispatch_continuation`
  already dispatches with the workflow's token (`github.py:635-643`). `l4 setup github` adds the default branch to
  the environment's deployment branch policies when it is not the base (SPEC §2 row `l4 setup github`), so the
  token secret resolves on a scheduled run.

The new module `src/l4/ci/relay.py`, called only from `run_command`'s stop (`orchestrator.py:1550`), after the
warning, never from `l4 plan --sweep`, so a job relays at most once:

```python
Relay = Literal["dispatched", "already_running", "no_work", "on_base", "not_github", "refused", "unsupported",
                "failed"]
def relay_to_base(app, cfg) -> Relay
```

In order:
1. Not in GitHub Actions: `not_github` (nothing printed; `pin_check` already skipped there).
2. `GITHUB_REF_NAME == cfg.forge.base_branch` (and `GITHUB_REF_TYPE` is `branch`): `on_base`. This run is the base's
   own copy, so a mismatch here is a different fault, and the existing warning and FIX stand alone. This is the loop
   guard: the relayed run is on the base with the base's pin, so `pin_check` passes there and it never relays.
3. May the base have work? `refresh_refs` (it fetches the unit refs and `refs/l4/plans/*`,
   `src/l4/vcs/refresh.py:16`, `:46`), then the answer is yes when any of these hold:
   - a plan ref whose `fold_plan` status is `active` or `waiting` (`local_plans`, `src/l4/yolo/commands.py:1891-1905`);
   - a row of `l4 plan` (`snapshots` + `compute_plan` + `with_plan_holds`, as `run_plan` builds them,
     `planner.py:426-432`) that is actionable;
   - a unit whose folded phase this harness does not know;
   - any exception in this step (logged at INFO with its first line).
   The first two signals overlap: `with_plan_holds` (`planner.py:242-264`) marks every unit a plan holds as not
   actionable, so a plan's units are found by the plan signal, and the `l4 plan` rows find work outside plans.
   When none holds: `no_work`. The stopped run runs the default branch's older harness. When that harness cannot read
   the base's state, it relays and lets the base's own run decide. That run exits with "nothing to do" before any
   lease when there is nothing (template header, `l4.github-action.yml:4-5`).
4. `forge.relay_run(base, exclude_run_id=GITHUB_RUN_ID)`. GitHub: `GET
   /repos/{r}/actions/workflows/l4.yml/runs?branch=<base>&per_page=20`. Any run other than this one whose `status` is
   `queued`, `pending`, `waiting`, `requested` or `in_progress` gives `already_running`. Otherwise `POST
   …/dispatches {"ref": base}` gives `dispatched`. 401 or 403 gives `refused`, 404 gives `unsupported`. A
   `ForgeUnavailable` (no token) gives `refused`. Any other error gives `failed`, logged.

Output (stderr, redacted, one line, after the existing `::warning::`):
- `dispatched`: `::notice::l4 relayed this run to <base>: started l4.yml on <base>, which runs the base's pin`
- `already_running`: `l4: not relayed: a run of l4.yml is already queued or running on <base>`
- `no_work`: `l4: not relayed: <base> has no active or waiting plan and no unit with a next step`
- `refused`, `unsupported`: `l4: not relayed: the token may not start a run on <base>; start one with: gh workflow run
  l4.yml --ref <base>` (`how_to_start`, `src/l4/state/retry.py:169-183`)
- `failed`: `l4: not relayed: <first line of the error>`

`outcome.json` gets `relay: <answer>` (only when the stop happened). The exit code stays 0 (L4-ADO-005).

Bootstrap [V by construction]: the stopped run executes the default branch's harness. The relay exists only once that
copy pins 0.4.19 or later. The consumer brings the default branch's copy up to the base once, which is the FIX that
CFG-008 already prints (`pin_guard.py:19-22`). After that, a later upgrade of the base alone is relayed.

GitLab [V]: `pin_check` returns `skip` outside GitHub Actions (`pin_guard.py:46-47`), and `l4 setup gitlab` creates the
`l4 sweep` schedule on the base ref (`src/l4/setup/gitlab.py:452-466`, `"ref": ref` from `base_ref()`). A GitLab
schedule runs the base's `.gitlab-ci.yml`. Nothing changes there.

The text of `l4 upgrade` (`stale_branches_note`, `src/l4/init/upgrade.py:440-469`) keeps "the schedule do that", and adds: `(on GitHub, once
the default branch's copy of l4.yml pins 0.4.19 or later: the scheduled run relays to <base>)`.

## D9. `l4 yolo status`: a run that ended without a record (L4-IMP-073)

Why origin has no `run.finished` even when the cancel handler ran [V]: GitHub cancels a job by signalling it [I: SIGINT,
then SIGTERM about 7.5 s later, then SIGKILL]. The handler raises `RunCancelled` (`cancel.py:79-83`), and `close()` on
a cancelled run appends `run.cancelled` and `run.finished` locally and pushes nothing (`orchestrator.py:1237-1242`,
W-D2). The open run on origin stays open for good.

What status does today [V]: `_describe` computes `next` (`commands.py:1715-1719`), then `last_activity` and `open_run`
(`:1720`, `_activity_of` `:1746-1777`). `_next_line` for `active` returns `nothing: CI advances the plan at each run
(…)` (`:1567-1571`). `_render` prints `open run: <id> started <t> ago, no end recorded[: <link>]` (`:1859-1862`).

Which command starts a run today [V]: `l4 yolo resume` refuses an active plan without `--extend-…`
(`commands.py:1421-1426`). `l4 retry` refuses an `implementing` unit ("the harness continues it at the next run",
`retry.py:78`). The command that exists is `how_to_start` (`retry.py:169-183`): `gh workflow run l4.yml --ref <base>`
on GitHub, `<project web URL>/-/pipelines/new?ref=<base>` on GitLab. `_next_line` already takes a `start` argument,
which `_describe` fills only for an answered wait (`:1717`).

Decision:
- An open run of the current unit is called **ended without a record** when either of these holds:
  1. Age: `now − started > job_timeout_s + 300`. `job_timeout_s` comes from the run's `run.started` (D1). For an older
     event it is `ci.time_budget` when that is not `auto`. Otherwise it is 180 minutes on GitHub
     (`JOB_TIMEOUT_MINUTES`, `src/l4/ci/github.py:22`) and on GitLab (the template's `timeout: 180m`). In that case
     the why says `assumed`. The 300 s allow for clock skew. `run.started` is written after the job started, so an age
     past the timeout means the job is over.
  2. The CI says so: `forge.ci_run_state(ci_url)` returns `completed` (GitHub `GET /repos/{r}/actions/runs/{id}`, the
     id parsed from `…/actions/runs/<id>[/attempts/<n>]`; GitLab `GET /projects/:id/jobs/<id>` from `…/-/jobs/<id>`).
     It is asked only when an open run exists and rule 1 does not already hold. No token, a URL that does not parse,
     or any error gives `unknown`, and the rule does not apply.
- `why` is one of `older than its job timeout (<n> min[, assumed]): likely the CI timeout` or `its CI run is
  <conclusion or status> (<cancelled|timed_out|failure|…>)`.
- Text: the open-run line becomes `open run: <id> started <t> ago, no end recorded: it ended without a record
  (<why>)[: <link>]`. It still starts with today's words.
- `--json`: `open_run.ended_without_record: true|false` and `open_run.why` (present when true).
- `Next:` for an `active` plan whose open run ended without a record: `the run <id> of <unit> ended without a record
  (<why>); the unit continues from its last pushed step: start a run on <base>: <how_to_start>`. This is one line, and
  `next` in `--json` is the same string. A `waiting` or `stopped` plan keeps its own Next, because the wait or stop
  names the step that comes first.

Does a stale open run block the next run? No [V]:
- The unit lease is a local `flock` on `$L4_CACHE/locks/<key>/<fw>/<name>.lock` that the kernel drops when the process
  dies (`src/l4/vcs/locks.py:1-7`, `:51-71`). A GitHub-hosted job is a fresh machine. On a self-hosted runner the
  killed process held the flock, and the kernel released it.
- No code reads `run.started` without `run.finished` as a lock. `OpenRun` is shown only (`status.py:288-307`,
  `commands.py:1746-1777`). The plan step reads `run.started` only to tell a unit that never began
  (`src/l4/yolo/cycle.py:1943`).
- The lock ref `refs/l4/locks/…` holds pending ledgers. Its commits are "born expired", with no acquire, heartbeat or
  takeover (`src/l4/state/pending.py:12`, `:279`). The plan ref uses `--force-with-lease` on its head, not a time
  lease (`src/l4/yolo/store.py:8-9`).
- GitHub's concurrency group releases when the cancelled job ends [I].
So no expiry needs to pass. The next run, however it starts, takes the lease at once.

## D10. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`:
  - L4-IMP-066 to L4-IMP-073 after L4-IMP-065, with the texts of this change's `specs/*/spec.md`.
  - SCN-IMP-332 to SCN-IMP-359 after SCN-IMP-331, before `### 23.8`, in the Part II form `#### SCN-IMP-NNN (+|−) Title
    · L4-IMP-0NN` with `- **Given**`/`- **When**`/`- **Then**`.
  - L4-IMP-012's *Implemented now* paragraph names the job start, the check before each step, the stop, the hand-back
    and the continuation, and keeps one *Still to do*: the WIP push (M2).
  - SCN-IMP-19 says the WIP snapshot is pushed in M2, and that the ledger and the branch are pushed now.
  - L4-ADO-005 gets one sentence on the relay (L4-IMP-072).
  - L4-YOLO-030 gets the suffix and the Next line (L4-IMP-073).
  - L4-CI-004 gets the designed-stop codes (L4-IMP-070).
  - The §3.2 sample comment of `soft_deadline_margin` says it must exceed the longest call that cannot be stopped.
  - Change-table row 56.
- `docs/runbook.md`: a section "A run ended without a record", with the status text, the cause, and `gh workflow run`.
  The stale-pin entry names the relay and the one-time update of the default branch.
- `docs/yolo-mode.md`: the schedule paragraph (relay), and status's open-run line.
- Skill `plugins/l4/skills/l4/references/operate.md`: two rows of the error table (`ended without a record`,
  `deadline_repeated`).
- `CHANGELOG.md`: `## 0.4.19 (unreleased)` above `## 0.4.18 (2026-10-20)` when it is not there (other 0.4.19 changes
  add the same heading; whoever merges second merges the lists). The lines are listed in `tasks.md`.

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.deadline`: `FLOOR_S = 600`, `MAX_STOPS = 2`, `DeadlineReached(BaseException)` with the fields of D2,
  `RunDeadline(at, clock, event, steps, started)` with `remaining_s()`, `fired()`, `fire()`; `arm`, `disarm`,
  `current`, `fired`, `check_before(phase, task, attempt, recorded)`, `estimate_s(phase, recorded, cap)`,
  `record_step(phase, seconds)`.
- `ProcOutcome.deadline: bool = False`; `GateResult.deadline: bool = False`.
- `job_remaining_s(cfg, environ, now, began)`: the start is `L4_JOB_STARTED_AT`, else `CI_JOB_STARTED_AT`, else
  `began`. `job_budget_s(cfg, environ) -> int | None` (the total before the margin) is factored out of it.
- Events: `deadline.reached{when, phase, task?, attempt?, round?, during?, gate?, left_s, estimate_s?, ran_s?,
  first?}` (`ran_s` and `first` for `when: during`);
  `step.timed{phase, task?, attempt?, round?, seconds}`; `breaker.tripped{reason: "deadline_repeated", task?, phase,
  stops}`; `run.started` + `job_timeout_s?: int`, `job_started_at?: str`; `run.finished` + `reason?: str`;
  `step.finished{status: "deadline"}`.
- `UnitRunResult.deferred: bool = False`; `CommandResult.deferred: Sequence[str] = ()`, `CommandResult.relay: str |
  None = None`; `outcome.json` `relay`.
- Exit reasons: `soft deadline: task <k> <phase> not started (<left> s left, step estimated <est> s); the next run
  continues it` and `soft deadline: task <k> <phase> stopped (<during>[ <gate>]); the next run runs it again`.
- Forge: `relay_run(ref, *, exclude_run_id: str | None) -> Literal["dispatched", "already_running", "refused",
  "unsupported"]` (GitHub; GitLab and local: `unsupported`); `ci_run_state(ci_url) -> Literal["running", "completed",
  "unknown"]` plus the conclusion text (GitHub and GitLab; local: `unknown`).
- `l4.ci.relay.relay_to_base(app, cfg) -> Relay`, with the eight values of D8.
- `l4.state.status.OpenRun` + `job_timeout_s: int | None = None` (from its `run.started`, read by `_activity`,
  `status.py:288-307`).
- Status JSON: `open_run.ended_without_record: bool` (always, when `open_run` is not null), `open_run.why: str` (only
  when true). Text suffix `: it ended without a record (<why>)`.
- Template step `job start` (the name), first in `steps:` of both GitHub templates.
- Test levers in `l4.agents.fake.Step`: `on_start: Callable[[RunRequest], None] | None = None` (called first in
  `run`), and the fake adapter honours `req.interrupt` and `deadline.fired()` (status `cancelled`).

## Collisions

- `delegate-answers` (0.4.19, another branch) defers a pass when `job_remaining_s` is below `delegate.timeout`, and
  starts one next run. After this change, that check should call `deadline.check_before("delegate", …)`, and its
  "next run" should go through `continue_left_units`, so that a run dispatches only one. Whoever merges second
  adapts. The ids do not overlap (L4-DLG-*).
- `yolo-go` (row 55) edits `_next_line` callers (D5 of that change reads the status's Next). This change adds one
  branch to `_next_line` (an `active` plan with an ended open run) and one argument. These are different hunks.
- `kiro-judge` and `opencode-v2` touch `src/l4/agents/*` adapters. This change touches `proc.py` and `fake.py`, not the
  adapters.
- All of them add `## 0.4.19 (unreleased)` to CHANGELOG and rows to the change table (55 is `yolo-go`; this is 56).

## Risks

- A call that D4 cannot stop (an HTTP judge, a `git` push or fetch, an e2e server started outside `ProcRunner`) can
  run past the soft deadline by its own timeout. The 20-minute default margin covers the known timeouts. A smaller
  `soft_deadline_margin` is the operator's risk, and the SPEC sample comment says so.
- The estimate can be too small (a green much longer than every red), and then the stop (D4) loses one step's work on
  a hosted runner. It can be too large (one slow recorded step), and then the run hands back early and pays for one
  more job's setup. The cap and the window of the last 10 records bound both.
- The relay's check for work runs the default branch's older harness on the base's ledgers. It fails open: an error or
  an unknown phase relays. A missed state that folds without error, and that only the newer harness finds actionable
  (a unit outside any plan), is not relayed. The base's next push or `l4 retry` starts it. An active or waiting plan is
  always relayed.
- A scheduled run that arrives while a continuation is pending replaces it in the concurrency group [I]. The relay
  then starts the base again, but that costs one more job's setup.
- The template step reaches a consumer only through `l4 upgrade`. The SPEC and CHANGELOG say so.

## Out of scope / follow-ups

- Push the WIP snapshot (L4-IMP-011 remote form, M2 fencing), so that a stopped step's work survives on a hosted
  runner.
- `budgets.max_iterations_per_unit` and `no_progress_iterations` have no reader (SCN-IMP-20 is not implemented), and
  task attempts are not counted across runs.
- The stale-pin stop runs after `load_app_config` (`orchestrator.py:1549-1550`, `planner.py:422-423`). A base config
  with a key that the older strict schema rejects makes the stopped run fail with exit 2 before the pin check, and so
  before the relay. The pin check should come first.
- `l4 status` (the unit view) prints the same `Open run: … no end recorded` (`status.py:573-576`) without the new
  classification.
- The agent's 1800-second time limit has no configuration key (`base.py:164`).
- An `l4` command that starts a run on the base (today's command is `gh workflow run`), for example `l4 ci start`.
- Verifier resume per step (verifier 1.19): a stopped round starts over.
- A concurrency group per ref, so that a scheduled run cannot cancel a pending continuation.

## Open questions (each with the recommended answer)

Decided by the owner's delegate on 2026-10-20: every recommended answer below is taken (1 as written, 2 constants,
3 dispatch, 4 the template step with today's behaviour as the fallback, 5 L4-IMP ids with cross-references, 6 ask
the forge, best effort).

1. Relay only when the base may have work (the brief, failing open), or always? Recommended: as written. It follows the
   brief, saves runner minutes on idle ticks, and fails open on anything the older harness cannot read. The
   alternative, relaying on every stopped tick, has no false negative and makes the same number of runs as a base that
   is the default branch.
2. `MAX_STOPS = 2`, `FLOOR_S = 600` and the cap: constants or configuration keys? Recommended: constants. The fix for a
   step that does not fit is a bigger job timeout, which is configured already.
3. A continuation when another unit of the run exits 11, 12 or 13: dispatch (as written), or keep "exit 10 only"
   (L4-CI-004's wording today)? Recommended: dispatch. The unit that was handed back must not wait for a schedule
   that, on this consumer, only works through the relay.
4. Job start through a template step (needs `l4 upgrade`), or by asking the API for the job's `started_at` at the
   start of `l4 run`? Recommended: the template step. It needs no network and no token, and the fallback is today's
   behaviour plus one INFO line.
5. Requirement ids: the relay and the status rule sit next to L4-ADO-005 and L4-YOLO-030, but the brief asked for
   L4-IMP-*. Recommended: keep L4-IMP-072 and L4-IMP-073 as instructed, with a cross-reference sentence in L4-ADO-005
   and L4-YOLO-030.
6. Ask the forge in `l4 yolo status` (one GET, only when an open run exists and is younger than its timeout), or rely
   on age alone? Recommended: ask, best effort. It names a job that died early (a lost runner) hours before the age
   rule would.
