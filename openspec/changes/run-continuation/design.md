## Context

`proposal.md` describes the three observations from a consumer repository. This change finishes L4-IMP-012 inside a
unit, makes the schedule work when the base branch is not the default branch, and makes `l4 yolo status` name a run
that ended without a record. It is built for 0.4.19 on top of the released 0.4.18 (f9116bad).

Labels: [V] verified in the code at f9116bad; [I] inferred, including every statement about GitHub's own behaviour
that this repository does not test.

One correction of the report's words: the event that ends a run is `run.finished` (`src/l4/state/ledger.py:263-264`,
`finish(exit_code)`), not `run.ended`. An "open run" is a `run.started` of `l4 run` with no `run.finished` of the same
run id (`src/l4/state/status.py:288-307`) [V]. This change keeps that name.

An independent review of the first draft (ACCEPT-WITH-FIXES) is folded in: the review's items are named where they
changed the design (M1 to M6, and the minor ones), and "Where this design departs from the review" says what was not
taken and why.

## Goals / Non-goals

Goals: when the job's budget is known, a run is never killed by the CI timeout. A step that cannot finish in time is
not started, or is stopped and handed back without counting as an attempt. Exactly one continuation follows. A step
that never fits halts by name instead of looping. A plan on a base that is not the default branch keeps moving on the
schedule. `l4 yolo status` gives the real next command when nothing will advance an active plan.

Non-goals:
- Pushing the WIP snapshot (L4-IMP-011's remote form, state-vcs-locks M2 with fencing). The snapshot stays a local
  ref (`src/l4/vcs/wip.py:1-6`, "never pushed") [V]. The work of a stopped step is lost on every runner, the same
  runner included: the hand-back commits the run's ledger on top of the head (`_commit_ledger`,
  `orchestrator.py:1332-1343`), so the next run's `plan_reconcile` finds a snapshot whose parent is no longer the head
  and answers `Rerun`, which drops it (`src/l4/state/reconcile.py:61-73`) [V]. The check before each step (D3) is the
  normal path, and the stop (D4) is the backstop.
- Session resume (L4-IMP-010). `RunRequest.resume_session_id` is read by `claude_code.py:137` and set by nobody [V].
- A new configuration key. The constants are named in "Contracts".

## D1. The deadline counts from the job's start (L4-IMP-066)

What the code does today [V]: `job_remaining_s` (`src/l4/orchestrator.py:1696-1715`) computes the total from
`ci.time_budget`, or for `auto` from GitLab's `CI_JOB_TIMEOUT` or GitHub's `L4_JOB_TIMEOUT_MINUTES`. It subtracts
`soft_deadline_margin`, then subtracts the time since `CI_JOB_STARTED_AT` when that is set, else since `began`.
`began` is set by `run_units` when it starts (`:1741-1743`, `waits.began = clock.now()`). GitHub sets no job start
variable [I]. On GitHub, the deadline therefore counts from the start of `run_units`. That is after the checkout, the
setup action, `l4 doctor`, `l4 plan --sweep` and the plan step (which may run a review) (`l4.github-action.yml:39-64`)
[V]. Those steps use the margin without being counted.

Decision:
- Both GitHub templates (`src/l4/ci/templates/l4.github.yml`, `l4.github-action.yml`) get a first step, before
  `actions/checkout`:
  ```yaml
      - name: job start
        run: echo "L4_JOB_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_ENV"
  ```
  It needs no credential and no input. `$GITHUB_ENV` makes the variable visible to every later step [I: GitHub's
  documented mechanism]. `l4 ci lint` (`src/l4/ci/lint.py`) accepts it [V: the lint checks permissions, triggers and
  concurrency, not the steps].
- `job_remaining_s` reads the start from `L4_JOB_STARTED_AT`, then `CI_JOB_STARTED_AT`, then `began`, in that order. A
  value that does not parse is skipped (as `CI_JOB_STARTED_AT` is today, `:1711-1714`). Python 3.11's
  `datetime.fromisoformat` reads the `Z` suffix [V: the project's minimum is 3.11].
- When a budget is known and neither variable is set, `run_units` logs once, as a WARNING (review: minor):
  `soft deadline: the job's start is unknown (no L4_JOB_STARTED_AT): counting from this run's start; l4 upgrade adds
  the step that records it`.
- `run.started` records `job_timeout_s` (the total before the margin) and `job_started_at` (ISO UTC, when known),
  through the `LedgerWriter.open` call in `run_unit_in_worktree` (`:1471-1477`, beside `**run_environment(...)`).
  Status reads them (D9).

A consumer gets the step with `l4 upgrade`, which renders the workflow again. Until then, the deadline counts from the
run's start, as today, and the run says so.

## D2. One run deadline (`src/l4/deadline.py`)

A leaf module (it imports nothing from `l4`), on the model of `l4.cancel` (`src/l4/cancel.py`: process-wide state,
an exception that `except Exception` does not catch) [V].

```python
FLOOR_S = 600                 # the smallest estimate of a step
MAX_STOPS = 2                 # counted stops of one task and phase before the unit halts (D7)
HISTORY = 10                  # the recorded steps of a phase the estimate reads

class DeadlineReached(BaseException):   # like RunCancelled: no `except Exception` turns it into a failure
    when: Literal["before", "during"]
    during: Literal["agent", "judge", "gate"] | None   # set by the raise sites of D4
    gate: str | None
    reason: str | None         # a `before` deferral that is not about time: "stopped at the last deadline: …"
    mark: StepMark | None      # a `before` deferral: the mark of the step that was not started (never set as `step`)

@dataclass(frozen=True)
class StepMark:                # review M1: what the raise sites cannot know
    phase: str                 # red | green | single | verify
    task: str | None
    attempt: int | None
    round: int | None
    started_at: datetime       # on the factory clock
    first: bool                # the first step of its run
    left_at_start_s: float
    estimate_s: float

@dataclass
class RunDeadline:
    at: datetime               # the soft deadline, on the factory clock
    clock: Clock               # `now()`; the run's SystemClock, a FakeClock in tests
    event: threading.Event     # set at `at` by the timer, or by `fire()`
    steps: dict[str, float]    # phase -> the longest step of that phase measured in this run
    started: int = 0           # steps started in this run (any unit)
    step: StepMark | None = None   # the step running now; None between steps
    def remaining_s(self) -> float
    def fired(self) -> bool                   # event.is_set()
    def fire(self) -> None                    # sets the event (the timer and the tests call it)

def arm(deadline: RunDeadline, *, timer: Callable[[float, Callable[[], None]], Timer] = threading.Timer) -> None
def disarm() -> None                          # cancels the timer, clears the current deadline
def current() -> RunDeadline | None
def fired() -> bool                           # current() is not None and current().fired()
def check_before(phase, task, attempt, round, recorded, stopped_last: bool, cap: float) -> None
def end_step() -> float                       # clears `step`, records the phase's measure, returns the seconds
```

The attribute is named `step`, not `current` as the review wrote it, because the module already has `current()`.

`run_units` (`src/l4/orchestrator.py:1718`) arms the deadline once, after it computes the first `job_remaining_s`,
when a budget is known. It disarms it in a `finally` around the loop. Before that, it copies `started` into the
`CommandResult` it returns (`steps_started`, review M2), because `continue_left_units` runs after `run_units` returns
(`:1634`), when `current()` is already None. The deadline is armed only inside `l4 run`'s units. The plan step
(`yolo_step`, which runs before `run_units`), `l4 verify`, `l4 retry` and every other command never see it. The existing
check between units (`:1746-1765`) reads the same object.

Why a run-wide object rather than an event threaded through every constructor: `ProcRunner` is created in six places
(the five adapters and `run_gate`) [V: `grep "ProcRunner()"`], and the verifier, the fix loop and the clarifier each
build their own `Workbench` or judge. One module read in `ProcRunner._wait` covers every process that a unit's run
starts.

## D3. Before a step: the estimate (L4-IMP-067)

Where [V]:
- Every implementer step goes through `run_task` (`src/l4/implementer/loop.py:266`). Before its loop, `run_task` calls
  `resume_red` (`:285`). When the branch holds this task's red checkpoint, that call runs `gates.setup` and a whole
  baseline test gate (`tdd.py:1500-1503`). The loop then calls `run_single` (`:294`), `run_red` (`:309`) or
  `run_green` (`:324`).
- A fall-back after a usage limit calls `run_task` again for the same task (`orchestrator.py:928-930`, `continue`).
- A fix unit's tasks go through the same `run_task` (`_fix`, `orchestrator.py:1143`).
- A verification round starts at `Orchestrator._verify` (`:1096`, `trigger = verify(self._ctx)`).

The checks (review M3):
1. At the top of `run_task`, before `resume_red`: the task's first step. Its phase is `single` for a chore, `green`
   when `_last_checkpoint(wb)` (`tdd.py:1463`) is this task's red, else `red`; its attempt is 1. The green step's clock
   starts here, so the setup and the baseline of a resumed red belong to the green step. A `run_task` called again
   after a fall-back is checked here too.
2. In the loop, before each `run_single`, `run_red` and `run_green`. `check_before` does nothing when the mark of the
   same phase, task and attempt is already current (the top check of point 1).
3. In `_verify`, before `verify(self._ctx)`.

`check_before(phase, task, attempt, round, recorded, stopped_last, cap)`, a no-op when `current()` is None:
- `left = remaining_s()`, `estimate = estimate_s(phase, recorded, cap)`.
- The first step of the run (`started == 0`) starts whenever `left > 0`. This mirrors "the first unit always starts"
  (`orchestrator.py:1733-1734`); a run that started nothing could not make progress.
- It builds the step's `StepMark(phase, task, attempt, round, now, first=(started == 0), left_at_start_s=left,
  estimate_s=estimate)` first.
- A step that is not the first is deferred when `left < estimate`, or when `stopped_last` (D7): raise
  `DeadlineReached(when="before", mark=that_mark)`, with `reason` `stopped at the last deadline: it starts only as the
  first step of a run` in the second case. `step` is not set: nothing started.
- Otherwise `started += 1` and `step = that_mark`.
- `end_step()` runs when the step returns or raises anything but `DeadlineReached`. It updates `steps[phase]` and
  appends `step.timed{task, phase, attempt, seconds}` (a round: `step.timed{phase: "verify", round, seconds}`).

The estimate: `estimate_s(phase, recorded, cap) = min(cap, max(FLOOR_S, steps.get(phase, 0), max(recorded, default=0)))`.
- `recorded` is the `seconds` of the unit's last `HISTORY` `step.timed` of that phase, and the `ran_s` of its stops
  of that phase (D7, a lower bound of a step's length), read from the unit's events as the workbench folds them
  (`_ledger_events`, `src/l4/implementer/tdd.py:1668`; the orchestrator's `_events()` for a round).
- When the phase has no measure in this run and none recorded, the longest step of any phase is used instead (this
  run's, then the recorded ones). That is the reported case: a 23.5-minute red, then a green with no history.
- The cap is per phase (review: minor). For red, green and single it is `RunRequest.timeout_s +
  duration_seconds(gates.timeout)`, 1800 s + 1800 s by default. The agent's time limit is the dataclass default
  (`src/l4/agents/base.py:164`, `timeout_s: int = 1800`), which no configuration key sets [V]; `gates.timeout` is
  `30m` (`src/l4/config/schema.py:248`) [V]. For a verification round it is `4 × gates.timeout`, 7200 s by default.
  The reason: a round runs several gates (setup, the test gate, the base tests, generated and audit tests) and its
  judges [V: the steps 0 to 9 of `verify_unit`, `ladder.py:522`, `:620-635`], and a stopped round starts over (no
  per-step resume yet). A round must not be
  started late on the cap of a single step. The four gates are an inference from the ladder's steps [I]. The cap
  keeps one outlier (a step that waited out a cool-down) from blocking every later step.

The reported case, step by step: the job's start is known (D1). At 155 minutes, `left = 180·60 − 20·60 − 155·60 =
300 s`. The green phase has no measure, so the estimate falls back to the red's 1410 s. 300 < 1410, so the green is
not started (SCN-IMP-335).

The clarifier gets no check before it starts: its calls are short, and D4 stops a CLI clarifier at the deadline. The
plan step runs before the deadline is armed (D2), so it is neither checked nor stopped. Its review has its own judge
timeouts.

## D4. During a step: the stop (L4-IMP-068)

What exists [V]: `ProcRunner._wait` (`src/l4/agents/proc.py:124-173`) already sends SIGINT to the process group when
`interrupt.is_set()`, then SIGKILL to the group after `INTERRUPT_GRACE_S = 5.0` (`:18`, `:159-166`, `:170`), and
returns `ProcOutcome(interrupted=True)`. Every adapter passes `req.interrupt` and maps `interrupted` to status
`cancelled` (`claude_code.py:219-221`, `codex.py:294`, `opencode.py:296`, `kiro_cli.py:180`, `command.py:117`). No
code ever sets `RunRequest.interrupt` (`base.py:168`, a fresh `Event`) [V: grep]. A gate runs through
`ProcRunner.run` without an interrupt (`src/l4/gates/runner.py:173-175`) [V]. SIGINT and not SIGTERM, as L4-IMP-012
requires: Claude exits 143 mid-turn on SIGTERM [V: SPEC L4-IMP-012].

Changes:
- `ProcRunner._wait` checks `deadline.fired()` first in each poll, before the time limit, the idle rule and the abort
  (review: minor; today the order is time limit, idle, abort, interrupt, `:150-166`). Once it has fired, the process
  gets SIGINT, then the 5 s grace, then SIGKILL of the group. The outcome is `ProcOutcome(interrupted=True,
  deadline=True)`, with `timed_out` and `stalled` false even when they fired in the same poll or during the idle
  grace. When the deadline wins, `_wait` also sets `watch.stopped_idle_s` back to None: the idle rule writes it the
  moment it fires (`proc.py:144-149`), and `agent_step` emits `agent.idle` from it (`tdd.py:827-831`). Adapters map
  `timed_out or stalled` to `timeout` before they look at `interrupted` (`claude_code.py:216-221`), so the deadline
  must win inside `_wait`. A process started after the deadline fired is
  stopped at once. Adapters need no change: they report `cancelled`.
- `run_gate` copies `outcome.deadline` to `GateResult.deadline` (a new field, default False).
- Three places turn a stopped process into `DeadlineReached(when="during", during=…)`. Each one is after the cleanup
  that already runs, so no caller changes. None of them knows the step: `_defer` fills the event from
  `RunDeadline.step` (review M1).
  1. `agent_step` (`src/l4/implementer/tdd.py:763`): after its `finally` (scratch dropped, protected paths and gate
     configuration reverted, ledger restored, environment checked, `:810-826`) and after `agent.finished` and the
     `budget.cost` events (`:827-846`, so a cost the CLI reported is kept). If `run.status == "cancelled"` and
     `deadline.fired()`, it raises `during="agent"`. The `wip_snapshots` box records `step.finished{status:
     deadline}`, distinct from `cancelled`, which keeps meaning a signal from CI. `agent.idle` is not emitted for a
     stop by the deadline (`:827-831` reads `watch.stopped_idle_s`, which `_wait` clears when the deadline wins).
  2. `Workbench.run_gate_spec` (`src/l4/implementer/workbench.py:386`): after its `finally` restores and after
     `gate.finished`. If `result.deadline`, it raises `during="gate", gate=spec.name`.
  3. `AgentJudge._run` (`src/l4/llm/agent_judge.py:116`, `:129`): if the run is `cancelled` and `deadline.fired()`, it
     raises `during="judge"`. This covers the verifier's CLI judges, the verifier agent, and a clarifier on a CLI
     (all with role `judge`, `agent_judge.py:102`).
- `DeadlineReached` is a `BaseException`. The verifier ladder has `except Exception` blocks that turn any error of
  a part of a step into a hold or a warning (`src/l4/verifier/ladder.py:672` scope, `:731` evidence, `:785` the S1
  shadow) [V]. A deadline raised as an `Exception` inside one of them would be swallowed there [I]. No `except
  Exception` lies between `agent_step` and `run_task` [V: grep of the implementer]. The judge step runs inside `try:
  _judge_step(...) finally: _calibrate(vc, run)` (`ladder.py:632-635`), so the calibration rows are still written
  when the judge is stopped; SCN-IMP-341 checks that through the real ladder. `run_unit` is the one place that catches
  it (D5).

What D4 cannot stop [I]: an HTTP model call (an API judge, `l4.llm` backends) and a `git` command. They end by their
own timeouts. The CLI judge's default is 600 s (`agent_judge.py:140`), and a CLI judge is stopped by D4 anyway. The
20-minute default margin is larger than every one of these timeouts. The risk is stated in Risks.

## D5. The hand-back (L4-IMP-069)

`Orchestrator.run_unit` (`src/l4/orchestrator.py:379-401`) catches `DeadlineReached` next to `(RoleUnavailable,
RoleLimit)` (`:398`) and calls `_defer(exc)`. It does not use `_park` (`:696-718`): that path takes the
`required_role_unavailable` edge to `waiting_capacity` with a `retry_after` and a capacity section, which is the wrong
state here.

`_defer(exc) -> ExitCode`:
1. Reads `mark = exc.mark` for `when == "before"`, else `mark = deadline.current().step`, and the clock. Appends `deadline.reached{when, phase, task, attempt, round,
   during, gate, left_s, left_at_start_s, estimate_s, ran_s, first, reason}` (keys that are None are left out).
   `ran_s = now − mark.started_at` (a `during` stop only). With no mark (a CLI clarifier, work before the unit's first check), `phase` is the
   unit's phase (`self.state.phase`), `first` is false, and there is no task: D7 never counts such a stop.
2. Applies D7. When the unit halts, it returns the halt's code.
3. Sets `_exit_reason` to one of (redacted, at most 300 characters):
   - `soft deadline: task <k> <phase> not started (<left> s left, step estimated <est> s); the next run continues it`
   - `soft deadline: task <k> <phase> not started (stopped at the last deadline: it starts only as the first step of a
     run); the next run continues it`
   - `soft deadline: task <k> <phase> stopped (<during>[ <gate>]); the next run runs it again`
   - for a verification round, `round <n>` in place of `task <k>`; with no mark, `<phase>` alone.
4. Clears `deadline.current().step`. Changes no phase. Fires no lifecycle edge. Counts no attempt: `run_task`'s
   `failures` and `task.attempt_failed` (`loop.py:342-350`) are skipped, because the exception leaves `run_task`
   before them.
5. Returns `ExitCode.CONTINUE` (10).

Then the existing `close(exit_code=10, failing=False)` (`:1229-1260`) appends `lock.released` and `run.finished`,
commits the run's ledger file only (`_commit_ledger`, `:1332-1343`: it stages the ledger path alone, so the stopped
step's uncommitted changes are not committed) and pushes the unit branch [V]. `run.finished` gets the new optional
`reason`: `LedgerWriter.finish(exit_code, reason=None)` (`ledger.py:263-264`), set from `_exit_reason` when the code is
10 and the reason starts with `soft deadline:`.

What the next run finds [V]: the worktree is built again from the pushed branch. A red that was committed and pushed
before the deadline (`tdd.py:1450-1456`, `wb.push()` after `task.red_committed`) is found by `resume_red`
(`tdd.py:1475`, `loop.py:285`), so only green runs. A step that was stopped starts over; its local WIP snapshot is
dropped (Non-goals).

A replayed held step that was stopped (review M4). `replay_step` emits `held.replayed` (`held_patch.py:836-840`)
before the green's gates run. A stop in those gates leaves `held.replayed` in the pushed ledger. The next run's
`find_replay` sees it (`:418`, `replayed = any(...)`), returns None, and an agent writes the step again: the person's
accept is lost. Rule: a `held.replayed` is **void** when a `deadline.reached{when: during}` of the same task and phase
follows it with no `task.red_committed`, `task.green_committed` or `task.done` of that task in between. One helper,
`held_patch.replay_voided(events, replayed)`, is used by the three readers of `held.replayed`: the spent check of
another check (`:392`), `find_replay` (`:418`) and the used-up notice (`:869`). A void replay is replayed again from
its saved patch, whose files are still in the branch: the hand-back commits only the ledger, so the queued removal
(`_queue_removal`, done by the next step commit) never happened.

`run_units`: after a unit whose result is a hand-back (`UnitRunResult.deferred = True`, a new field), no further unit
starts. The units left get `not started: soft deadline (…)`, as today (`:1748-1764`). `CommandResult` gets `deferred:
Sequence[str]`, the ids of the units handed back, and `steps_started: int` (D2).

## D6. Exactly one continuation (L4-IMP-070)

Today [V]: `continue_left_units` (`orchestrator.py:1675-1693`) dispatches only when `result.code == CONTINUE`, a unit
was `not started: soft deadline`, `ci.continuation == "dispatch"`, and the run is in CI. Then `_start_next_run`
(`:1651-1667`), the plan's own trigger, can start a second run in the same `l4 run` (`:1634-1635`).
`dispatch_continuation` on GitHub sends nothing when a run is `queued` (`src/l4/forge/github.py:635-643`); on GitLab it
answers `unsupported` (`gitlab.py:371-373`), while `start_run` on GitLab already starts a pipeline
(`POST /pipeline`, `gitlab.py:375-387`) [V].

Changes:
- The condition becomes: (a unit was left at the soft deadline, or `result.deferred` is not empty), and the run's code
  is a designed stop (`ExitCode` in `CI_ALLOWED = (10, 11, 12, 13)`, `exitcodes.py:38`), and `ci.continuation ==
  "dispatch"`, and the run is in CI. Before, a run where unit A waited for a person (11) and unit B was left at the
  deadline (10) exited 11 and dispatched nothing, so B waited for the schedule [V: `most_severe` order,
  `exitcodes.py:30`]. The order matters: a hand-back stops every later unit (D5), so the only way to have both is a
  unit that parks first and a unit handed back after it (SCN-IMP-346 is written that way).
- No step started in the run (`result.steps_started == 0`, which only happens when the time was gone before the first
  step, review M2): no continuation, and `run_command` clears `step.start_next_run`, so `_start_next_run` sends nothing
  either. A WARNING says `continuation: not requested: no step fitted before the soft deadline (<s> s left at the first
  step); raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES or ci.time_budget`. Otherwise every run would find the same
  lack of time.
- One dispatch per `l4 run`. When `continue_left_units` returns `dispatched` or `already_queued`, `run_command`
  clears `step.start_next_run` before `_start_next_run`. The continuation runs the plan step too, so nothing is lost.
- GitHub keeps today's guard: nothing is sent when a run is `queued` on the base. It must not add an `in_progress`
  check: the run that dispatches is itself in progress on the base and would always find itself (SCN-IMP-365).
- GitLab (review: minor, decided): `GitLabForge.dispatch_continuation(ref)` lists the base's pipelines (`GET
  /projects/:id/pipelines?ref=<base>&per_page=20`). Any pipeline other than `CI_PIPELINE_ID` whose status is `created`,
  `waiting_for_resource`, `preparing`, `pending` or `scheduled` gives `already_queued`, and `running` is not counted,
  for the same reason as on GitHub [I: GitLab's documented statuses]. Otherwise it calls `start_run(ref)`: `started`
  gives `dispatched`, and `refused` or `unsupported` gives `unsupported`, with a warning that names the token rule. The
  `l4` job's rules accept the source `api` (`gitlab.py:375-378`) [V]. L4-CI-004's "GitLab answers `unsupported` until
  forge-and-ci 2.6" changes with it.

The order holds [V]: each unit's `close()` pushes inside `run_unit_in_worktree` (`:1518-1526`), and
`continue_left_units` runs after every unit (`:1634`). The ledger and the branch are on origin before the dispatch.

What GitHub does with the dispatched run [I: documented concurrency behaviour]: the job's `concurrency: group: l4,
cancel-in-progress: false` (`l4.github.yml:28-30`) keeps the continuation `pending` until this job ends. A newer run
queued in the same group (a scheduled run, for one) cancels the pending continuation and takes its place. That newer
run either does the work itself (its copy pins the base's harness: `pin_check` passes and the `base checkout` step put
the base's tree in place, `l4.github-action.yml:46-54`) or is stopped and relays (D8), which then finds no other run
waiting on the base and dispatches. Either way one base run follows. "Where this design departs from the review" says
why the group stays as it is.

## D7. A step that never fits halts (L4-IMP-071)

`budgets.max_iterations_per_unit` and `no_progress_iterations` exist in the schema only: nothing reads them [V: grep].
Attempts are counted in memory per `run_task` call (`loop.py:274-282`), so they do not carry across runs [V]. Without a
guard, a step that takes longer than one job (agent, then many gate runs) would be stopped in every run. Each
continuation would start it again and throw away three hours of work.

The window of a task and phase starts after the last `task.red_committed`, `task.green_committed` or `task.done` of
that task. The window of a verification round starts after the last `verify.verdict` (the round boundary,
`ladder.py:1484`: `round_no = last_verdict.round + 1`). A `unit.retried`, `unit.resumed` or `unit.restarted` starts both
windows again (review: minor) [V: the fold treats them as a resume and a restart, `fold.py:573-575`].

Rules, from the unit's events in the window:
- **Counted stop**: a `deadline.reached{when: during}` with a task and phase (or round) that was the first step of its
  run (`first`), or that started with at least its estimate left (`left_at_start_s >= estimate_s`).
- **First only after a stop**: while the window holds any `during` stop of this task and phase, `check_before` gets
  `stopped_last=True`, so the step starts only as the first step of a run.
- **Halt**: when `_defer` records a counted stop and the window then holds 2 (`MAX_STOPS`):
  - append `breaker.tripped{reason: "deadline_repeated", task, phase, stops: 2}`;
  - `return self._halt("deadline_repeated", detail)` (`:1075`), with `detail` = `task <k> <phase> was stopped at the
    soft deadline twice (it ran <m> min of the <b> min it had): it does not fit in one job; raise timeout-minutes and
    L4_JOB_TIMEOUT_MINUTES (or ci.time_budget), or split the task, then l4 retry --unit <U> --reason TEXT`.
- Never counted: a step that was not started (`when: before`, it ran nothing), and a stop with no mark (D5).

A halted current unit stops a delivery plan (L4-YOLO-013), as any halt does. `l4 retry` brings the unit back
(halted → `previous_phase`, `retry.py:1-20`) [V], and its `unit.retried` starts the window again. A halt with no task
(a verification round) is already a case today (`baseline_failed` has none); the readers of `breaker.tripped` and
`halt_task` (`l4 status`'s cause, the sticky section, `note_binding`) must take `task: null`, which task 4.2 checks.

Why both conditions count, where the review proposed the estimate test alone:
- `left_at_start_s >= estimate_s`: the step had at least the time it was expected to need. A late start on a fair
  estimate that still did not finish counts.
- `first`: the step had the most time one job gives. With the "first only after a stop" rule, every restart of a
  stopped step is a first step. If a first step that started with less than its estimate did not count (a setup that
  ate most of the job), each run would start it, lose it, and dispatch the next: a loop of whole jobs. Counting it
  halts after two such jobs, and the halt's text (raise the job timeout) is the right fix for that case too.
- Termination: after a stop, the step starts only as the first step of a run. A first step always starts while time
  is left, and its stop always counts. So a step that never fits halts at its second stop, and any run in between
  either made progress on an earlier step of the run's order or dispatched nothing (L4-IMP-070).
- No false halt: a step that fits in a whole job is stopped at most once (late), then runs as the first step of the
  next run and finishes.

## D8. A run on a stale copy of the workflow relays to the base (L4-IMP-072)

What the code does today [V]:
- `stale_pin_stop` (`src/l4/ci/pin_guard.py:65-73`) returns the warning when `pin_check` finds a mismatch. That is only
  in GitHub Actions with `harness.delivery: action` (`:44-62`; it skips outside `GITHUB_ACTIONS` and for another
  delivery). `l4 plan --sweep` (`src/l4/planner.py:423`) and `l4 run` (`src/l4/orchestrator.py:1550-1552`) print it and
  exit 0, but only after `load_app_config` (`planner.py:422`, `orchestrator.py:1549`).
- `load_config` is strict (`schema.py:78`, `extra="forbid"`). `l4 doctor` loads it first and exits 2 on a schema error
  (`doctor/run.py:46`). The template's steps run `doctor`, then `plan`, then `run`, and none has `if: always()` except
  `status` (`l4.github-action.yml:57-67`). So a base configuration with a key that the default branch's older harness
  does not know makes the stopped job fail at `doctor`, before any pin check (review M5).
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

### Before the configuration (review M5)

New module `src/l4/ci/relay.py`:

```python
LENIENT_KEYS = ("harness.delivery", "harness.repository", "forge.base_branch", "forge.branch_prefix",
                "forge.token_env", "forge.platform", "spec.openspec.root", "spec.kiro.root")
def lenient_settings(repo: Path) -> dict[str, str]      # yaml.safe_load of .l4/config.yaml, no schema; {} when unreadable
def early_pin_stop(repo: Path, environ: Mapping[str, str], *, command: str) -> EarlyStop | None
Relay = Literal["dispatched", "already_running", "no_work", "on_base", "refused", "unsupported", "failed"]
def relay_to_base(repo, environ, settings) -> Relay
```

`early_pin_stop` is the first thing `run_doctor` (with `--ci`), `run_plan` (with `--sweep`) and `run_command` do,
before `load_app_config`. It returns None unless all of these hold: `GITHUB_ACTIONS=true`; the lenient delivery
(`harness.delivery`, else `fetched` when `harness.repository` is set, else `vendored`, as `effective_delivery` derives
it, `schema.py:124-131`) is `action`; and the checked-out `.github/workflows/l4.yml`'s pin (`read_pin`) differs from
`harness_commit()`. On a mismatch:
1. It prints the existing `::warning::` text (`pin_guard.py:65-73`, through the pre-config redactor `redactor_for`).
2. It relays once per job. The job's marker is `$RUNNER_TEMP/l4-relay.json`, which holds the answer and the run id
   [I: `RUNNER_TEMP` is emptied for each job]. A command that finds the marker prints `l4: relayed earlier in this job
   (<answer>)` and sends nothing. Without `RUNNER_TEMP`, the marker goes to `.l4-out/relay.json` of the checkout.
3. `l4 plan --sweep` and `l4 run` return exit 0 at once. `l4 run` records `relay` in `outcome.json` (its own answer,
   or the marker's). `l4 doctor --ci` goes on. When its `load_app_config` then raises a schema error, it prints
   `::warning::the base's .l4/config.yaml does not load in this harness (<first line>): expected on a copy of the
   workflow that is not the base's` and exits 0.

The existing `stale_pin_stop` after the configuration stays, for a configuration that the lenient read could not
parse. It prints the warning and does not relay.

The relay's forge and token come from the lenient settings and the job environment: the base is `L4_BASE_BRANCH`
(template, `l4.github-action.yml:36`), else `forge.base_branch`; the token is `environ[forge.token_env or
"L4_FORGE_TOKEN"]`; the forge is built from an `L4Config` validated from the lenient keys alone (these keys exist
since 0.4.0). A validation error of those keys gives `failed`, logged, and no dispatch.

### `relay_to_base`, in order

1. `GITHUB_REF_NAME == base` (and `GITHUB_REF_TYPE` is `branch`): `on_base`. This run is the base's own copy, so a
   mismatch here is a different fault, and the existing warning and FIX stand alone. This is the loop guard: the
   relayed run is on the base with the base's pin, so `pin_check` passes there and it never relays.
2. May the base have work? Read with git only (review M5), after `git fetch origin +refs/l4/plans/*:refs/l4/plans/*`
   with the token's auth header (`fetch_auth_config` of the lenient `L4Config`). Yes when any of these hold:
   - a plan ref whose ledger folds (`fold_plan`, which needs no configuration) to `active` or `waiting`;
   - a plan ref listed by `for-each-ref` whose ledger cannot be read or folded (`local_plans` drops those,
     `yolo/commands.py:1891-1905`; here they count as work, review: minor);
   - a branch `refs/remotes/origin/<branch_prefix>*` (the checkout fetched every branch, `fetch-depth: 0`);
   - a unit folder on the checked-out base: `<spec.openspec.root>/changes/<name>/tasks.md` with `<name>` not
     `archive`, or `<spec.kiro.root>/<name>/tasks.md` (defaults `openspec` and `.kiro/specs`, `schema.py:138`, `:142`);
   - any exception in this step (logged at INFO with its first line).
   When none holds: `no_work`. The base's own run decides the rest: it exits with "nothing to do" before any lease
   when there is nothing (template header, `l4.github-action.yml:4-5`).
3. `forge.relay_run(base, exclude_run_id=GITHUB_RUN_ID)`. GitHub: `GET
   /repos/{r}/actions/workflows/l4.yml/runs?branch=<base>&per_page=20`. Any run other than this one whose `status` is
   `queued`, `pending`, `waiting`, `requested` or `in_progress` gives `already_running`. Otherwise `POST
   …/dispatches {"ref": base}` gives `dispatched`. 401 or 403 gives `refused`, 404 gives `unsupported`. A
   `ForgeUnavailable` (no token) gives `refused`. Any other error gives `failed`, logged.

Output (stderr, redacted, one line, after the existing `::warning::`):
- `dispatched`: `::notice::l4 relayed this run to <base>: started l4.yml on <base>, which runs the base's pin`
- `already_running`: `l4: not relayed: a run of l4.yml is already queued or running on <base>`
- `no_work`: `l4: not relayed: <base> has no active or waiting plan, no unit branch and no unit folder`
- `refused`, `unsupported`: `l4: not relayed: the token may not start a run on <base>; start one with: gh workflow run
  l4.yml --ref <base>` (`how_to_start`'s GitHub text, `src/l4/state/retry.py:174-175`)
- `failed`: `l4: not relayed: <first line of the error>`

The exit code stays 0 (L4-ADO-005).

### What still needs a person, once

The stopped run executes the default branch's harness. The early stop and the relay exist only once that copy pins
0.4.19 or later. So the consumer copies `.github/workflows/l4.yml` to the default branch once (or promotes the base to
it), which is the FIX that CFG-008 already prints (`pin_guard.py:19-22`). After that, a later upgrade of the base
alone is relayed. The runbook and the CHANGELOG say this in these words.

Two places say it before it bites:
- `l4 upgrade`'s `_default_branch_reminder` (`src/l4/init/upgrade.py:272-280`, review: minor). Today it says nothing
  when `origin/HEAD` is unset (`:275-277`). With a known default branch that is not the base, it keeps its text and
  adds `; from 0.4.19 on, that copy's scheduled runs relay to <base>`. With `origin/HEAD` unset, it says: `if the
  default branch is not <base>, copy .github/workflows/l4.yml there once: GitHub runs the schedule from that copy`.
  `stale_branches_note` (`:440-469`) is unchanged.
- The base's own run (L4-IMP-074, review M6 b). In `run_command` on the base (`GITHUB_REF_NAME == base`, GitHub
  Actions, `action` delivery, after the configuration loads), `default_copy_warning(cfg, repo, environ)` reads the
  default branch from the event payload (`GITHUB_EVENT_PATH`, `repository.default_branch`) [I: present in `push`,
  `schedule` and `workflow_dispatch` payloads]. When it is not the base and `refs/remotes/origin/<default>` exists, it
  reads that copy's pin with `_branch_pin(git, ref, "action")` (`upgrade.py:421-433`) and the release from the
  comment of its `uses:` line (`# vX.Y.Z`, as the template writes it, `l4.github-action.yml:2-3`; YAML drops comments,
  so the line is read as text). When the pin differs from the base's, it prints once:
  `::warning::the default branch <d>'s copy of .github/workflows/l4.yml pins <a7>[ (vX.Y.Z)], not <b7> as <base> does:
  its scheduled runs stop on the pin check[ and, being older than 0.4.19, cannot relay to <base>]; copy
  .github/workflows/l4.yml to <d> once (or promote <base>)`. An unknown default branch, the base as default, the same
  pin, or another delivery prints nothing.

GitLab [V]: `pin_check` returns `skip` outside GitHub Actions (`pin_guard.py:46-47`), and `l4 setup gitlab` creates the
`l4 sweep` schedule on the base ref (`src/l4/setup/gitlab.py:452-466`, `"ref": ref` from `base_ref()`). A GitLab
schedule runs the base's `.gitlab-ci.yml`. Nothing changes there.

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
- `_describe` computes the open run before `next`, and `_next_line` gets `open_run` and `base_runs`.
- An open run of the current unit is called **ended without a record** when either of these holds:
  1. Age (only when its `run.started` has a `ci_url`, review: minor; a local run has no job timeout): `now − started >
     job_timeout_s + 300`. `job_timeout_s` comes from `OpenRun.job_timeout_s` (D1). For an older event it is
     `ci.time_budget` when that is not `auto`. Otherwise it is 180 minutes on GitHub (`JOB_TIMEOUT_MINUTES`,
     `src/l4/ci/github.py:22`) and on GitLab (the template's `timeout: 180m`), and the why says `assumed`. The 300 s
     allow for clock skew. `run.started` is written after the job started, so an age past the timeout means the job is
     over.
  2. The CI says so, asked only when rule 1 does not already hold and a token is available:
     `forge.ci_run_state(ci_url)` returns `completed`. GitHub: `GET /repos/{r}/actions/runs/{id}`, or
     `…/runs/{id}/attempts/{n}` when the URL names an attempt (a re-run, review: minor). GitLab: `GET
     /projects/:id/jobs/<id>` from `…/-/jobs/<id>`. The GET has a timeout of at most 10 s. No token, a URL that does not
     parse, or any error gives `unknown`, and the rule does not apply.
- `why` is one of `older than its job timeout (<n> min[, assumed]): likely the CI timeout` or `its CI run is
  <status> (<conclusion>)`.
- Text: the open-run line becomes `open run: <id> started <t> ago, no end recorded: it ended without a record
  (<why>)[: <link>]`. It still starts with today's words.
- `--json`: `open_run.ended_without_record: true|false` and `open_run.why` (present when true).
- `Next:` for an `active` plan:
  - its open run ended without a record: `the run <id> of <unit> ended without a record (<why>); the unit continues
    from its last pushed step: start a run on <base>: <how_to_start>`;
  - no open run that may still be running, and `forge.base_runs(base)` is 0 (review M6 d): `nothing is running or
    queued on <base>: start a run on <base>: <how_to_start>`. `base_runs` is the count of the base's runs of the
    harness's CI that are queued, pending, waiting, requested or in progress (GitHub, the listing of `relay_run`;
    GitLab, pipelines `created` to `running`). It is asked with the same token and timeout rules, and `None`
    (unknown) keeps today's line;
  - otherwise today's line.
  It is one line, and `next` in `--json` is the same string. A `waiting` or `stopped` plan keeps its own Next, because
  the wait or stop names the step that comes first.
- Why the forge and not the ledger for "nothing will advance it": a run that ended with a record does not record what
  it dispatched (`_start_next_run` and `continue_left_units` only log it, `orchestrator.py:1651-1693`), and the
  schedule is invisible to the ledger. The forge's list of queued and running runs is the one fact that says whether
  anything is coming.

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
  - L4-IMP-066 to L4-IMP-074 after L4-IMP-065, with the texts of this change's `specs/*/spec.md`.
  - SCN-IMP-332 to SCN-IMP-376 after SCN-IMP-331, before `### 23.8`, in the Part II form `#### SCN-IMP-NNN (+|−) Title
    · L4-IMP-0NN` with `- **Given**`/`- **When**`/`- **Then**`.
  - L4-IMP-012 (`SPEC.md:2546-2557`): the *Implemented now* paragraph names the job start, the check before each step,
    the stop, the hand-back, the continuation and the halt; *Still to do* keeps only the WIP push (M2).
  - SCN-IMP-19 (`SPEC.md:7082-7086`): its **Then** becomes: SIGINT is sent, the ledger and the unit branch are pushed
    (the WIP snapshot stays local until M2), one continuation is dispatched, the ledger iteration becomes N+1, exit 10.
  - L4-CI-004 (`SPEC.md:5530-5534`): a continuation follows a hand-back or a unit left at the soft deadline when the
    exit code is 10, 11, 12 or 13; on GitLab it is a pipeline on the base (`start_run`), and none is started when one
    waits.
  - L4-ADO-005 (`SPEC.md:308-318`): one sentence on the early stop and the relay (L4-IMP-072) and one on the base's
    warning (L4-IMP-074).
  - L4-YOLO-030 (`SPEC.md:4850-4856`): the suffix and the Next lines (L4-IMP-073).
  - The §3.2 sample comment of `soft_deadline_margin` (`SPEC.md:938`) says it must exceed the longest call that
    cannot be stopped.
  - Change-table row 56.
- `docs/runbook.md`: a section "A run ended without a record", with the status text, the cause, and `gh workflow run`.
  The stale-pin entry names the relay and says, in these words, "copy `.github/workflows/l4.yml` to the default branch
  once (or promote the base): until that copy pins 0.4.19 or later, its scheduled runs cannot relay".
- `docs/yolo-mode.md`: the schedule paragraph (relay, and the one-time copy), and status's open-run and Next lines.
- Skill `plugins/l4/skills/l4/references/operate.md`: three rows of the error table (`ended without a record`,
  `nothing is running or queued`, `deadline_repeated`).
- `CHANGELOG.md`: `## 0.4.19 (unreleased)` above `## 0.4.18 (2026-10-20)` when it is not there (other 0.4.19 changes
  add the same heading; whoever merges second merges the lists). The lines are listed in `tasks.md`.

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.deadline`: `FLOOR_S = 600`, `MAX_STOPS = 2`, `HISTORY = 10`; `DeadlineReached(BaseException)` with `when`,
  `during`, `gate`, `reason`, `mark` (set for `when: before`); `StepMark(phase, task, attempt, round, started_at, first, left_at_start_s,
  estimate_s)`; `RunDeadline(at, clock, event, steps, started, step)` with `remaining_s()`, `fired()`, `fire()`;
  `arm(deadline, *, timer=threading.Timer)`, `disarm()`, `current()`, `fired()`, `check_before(phase, task, attempt,
  round, recorded, stopped_last, cap)`, `end_step() -> float`, `estimate_s(phase, recorded, cap)`,
  `cap_s(phase, gates_timeout_s, agent_timeout_s=1800)` (red, green, single: agent + gate; verify: 4 × gate).
- `ProcOutcome.deadline: bool = False` (when true, `interrupted` is true, `timed_out` and `stalled` are false, and
  the `ActivityWatch`'s `stopped_idle_s` is None);
  `GateResult.deadline: bool = False`.
- `job_remaining_s(cfg, environ, now, began)`: the start is `L4_JOB_STARTED_AT`, else `CI_JOB_STARTED_AT`, else
  `began`. `job_budget_s(cfg, environ) -> int | None` (the total before the margin) is factored out of it.
- Events: `deadline.reached{when, phase, task?, attempt?, round?, during?, gate?, left_s, left_at_start_s?,
  estimate_s?, ran_s?, first?, reason?}`; `step.timed{phase, task?, attempt?, round?, seconds}`;
  `breaker.tripped{reason: "deadline_repeated", task?, phase, stops}`; `run.started` + `job_timeout_s?: int`,
  `job_started_at?: str`; `run.finished` + `reason?: str`; `step.finished{status: "deadline"}`.
- `UnitRunResult.deferred: bool = False`; `CommandResult.deferred: Sequence[str] = ()`, `CommandResult.steps_started:
  int = 0`, `CommandResult.relay: str | None = None`; `outcome.json` `relay`.
- Exit reasons: the four texts of D5 step 3.
- `held_patch.replay_voided(events, replayed: LedgerEvent) -> bool`.
- Forge: `relay_run(ref, *, exclude_run_id: str | None) -> Literal["dispatched", "already_running", "refused",
  "unsupported"]` (GitHub; GitLab and local: `unsupported`); `base_runs(ref, *, exclude_run_id: str | None = None) ->
  int | None` (GitHub and GitLab; local: None); `ci_run_state(ci_url) -> tuple[Literal["running", "completed",
  "unknown"], str]` (the status or conclusion text; GitHub and GitLab; local: `unknown`); GitLab
  `dispatch_continuation` as D6.
- `l4.ci.relay`: `LENIENT_KEYS`, `lenient_settings(repo)`, `early_pin_stop(repo, environ, *, command) -> EarlyStop |
  None` (`EarlyStop(exit_code, relay)`), `relay_to_base(repo, environ, settings) -> Relay` (seven values, D8),
  `default_copy_warning(cfg, repo, environ) -> str | None`; marker `$RUNNER_TEMP/l4-relay.json` `{run_id, answer}`.
- `l4.state.status.OpenRun` + `job_timeout_s: int | None = None` (from its `run.started`, read by `_activity`,
  `status.py:288-307`).
- Status JSON: `open_run.ended_without_record: bool` (always, when `open_run` is not null), `open_run.why: str` (only
  when true). Text suffix `: it ended without a record (<why>)`. Next texts of D9.
- Template step `job start` (the name), first in `steps:` of both GitHub templates.
- Test levers in `l4.agents.fake.Step`: `on_start: Callable[[RunRequest], None] | None = None` (called first in
  `run`), and the fake adapter honours `req.interrupt` and `deadline.fired()` (status `cancelled`).
- Tests: `tests/conftest.py`'s `_AMBIENT_CI` (`:31-33`) also strips `L4_JOB_.*`, so a job's
  `L4_JOB_TIMEOUT_MINUTES` cannot arm a deadline in the harness's own CI (today it strips `CI_.*`, `GITHUB_.*`,
  `RUNNER_.*` and a few more, not `L4_JOB_*`), and an autouse fixture calls `deadline.disarm()` after each test.

## Collisions

- `delegate-answers` (0.4.19, another branch) defers a pass when `job_remaining_s` is below `delegate.timeout`, and
  starts one next run. After this change, that check should call `deadline.check_before("delegate", …)`, and its
  "next run" should go through `continue_left_units`, so that a run dispatches only one. Whoever merges second
  adapts. The ids do not overlap (L4-DLG-*).
- `yolo-go` (row 55) edits `_next_line` callers (D5 of that change reads the status's Next). This change adds two
  branches to `_next_line` (an `active` plan with an ended open run, and one with nothing queued) and two arguments.
  These are different hunks.
- `kiro-judge` and `opencode-v2` touch `src/l4/agents/*` adapters. This change touches `proc.py` and `fake.py`, not the
  adapters.
- All of them add `## 0.4.19 (unreleased)` to CHANGELOG and rows to the change table (55 is `yolo-go`; this is 56).

## Risks

- A call that D4 cannot stop (an HTTP judge, a `git` push or fetch, an e2e server started outside `ProcRunner`) can
  run past the soft deadline by its own timeout. The 20-minute default margin covers the known timeouts. A smaller
  `soft_deadline_margin` is the operator's risk, and the SPEC sample comment says so.
- SIGINT reaches the agent's process group, which under `bwrap --unshare-pid` is the sandbox's own process; whether
  bwrap passes the SIGINT to the CLI inside is not tested here [I]. The SIGKILL of the group after 5 s ends it either
  way. A CLI that is killed before it reports its usage loses that step's cost in the ledger.
- The estimate can be too small (a green much longer than every red), and then the stop (D4) loses one step's work. It
  can be too large (one slow recorded step), and then the run hands back early and pays for one more job's setup. The
  cap, the window of the last 10 records and the "first only after a stop" rule bound both.
- Every continuation is one more run of a delivery plan: a plan with `limits.runs` stops with `limit_runs` sooner
  (`yolo/limits.py:97-98`) [V]. The CHANGELOG says so, and `l4 yolo resume --extend-runs N` raises it.
- The relay's check for work reads git only, so it is crude: any unit branch or unit folder counts. A base with an
  in-review unit relays on every scheduled tick, and the base's run then exits with "nothing to do". This is the same
  number of runs as a base that is the default branch.
- A scheduled run that arrives while a continuation is pending replaces it in the concurrency group [I]. The scheduled
  run then does the work itself, or relays (D6). When the relay is refused (no token in the default branch's
  environment), the continuation is lost until the next trigger, and the stopped run's line names `gh workflow run`.
- The template step reaches a consumer only through `l4 upgrade`. The SPEC and CHANGELOG say so.

## Where this design departs from the review

- **M6 a, a concurrency group that depends on whether the run is on the base: not taken.** The group `l4` is what
  serialises every working run of the harness on GitHub. On the steady path, the default branch's copy pins the
  base's harness, `pin_check` passes (`pin_guard.py:60-61`), and the scheduled run does the work itself on the base's
  tree (the `base checkout` step, `l4.github-action.yml:46-54`). A push to a unit branch also runs `l4 run` on the
  base's tree. The template's single group `l4` (`l4.github.yml:28-30`) is the CI platform's serialisation that SPEC
  L4-LCK-001 (`SPEC.md:4257`) calls primary (the SPEC names the per-unit form `l4-<unit>` of the matrix job, M1), and
  the unit lease is a local flock, "correct on one runner" (`locks.py:1-7`): two GitHub-hosted jobs in different
  groups run on two machines and both take the lease of the same unit. `group: l4-${{ github.ref_name == '<base>' &&
  'base' || github.ref_name }}` puts the default branch's scheduled run and each unit-branch push in groups of their
  own, so they would run `l4 run` at the same time as a base run, on the same units. The case the group change aims at
  (a scheduled run that cancels a pending continuation) already ends in one base run: the scheduled run works, or it
  relays because nothing else waits on the base (D6, Risks). A variant that sends only scheduled runs of another ref to
  their own group would be safe only if those runs never worked, which doubles the jobs of every tick on the steady
  path. Both are listed in follow-ups.
- **D7 counts a stop of the first step even when it started with less than its estimate.** The review asked to
  replace `first` by `left_at_start_s >= estimate_s`. Both are kept, with OR: without `first`, a step whose every run
  starts it as a starved first step would loop forever (D7, "Why both conditions count").
- **The attribute is `RunDeadline.step`, not `RunDeadline.current`**, because the module already has `current()`.

## Out of scope / follow-ups

- Push the WIP snapshot (L4-IMP-011 remote form, M2 fencing), and make `plan_reconcile` restore it on top of a
  ledger-only commit, so that a stopped step's work survives.
- `budgets.max_iterations_per_unit` and `no_progress_iterations` have no reader (SCN-IMP-20 is not implemented), and
  task attempts are not counted across runs.
- `l4 status` (the unit view) prints the same `Open run: … no end recorded` (`status.py:573-576`) without the new
  classification.
- The agent's 1800-second time limit has no configuration key (`base.py:164`).
- An `l4` command that starts a run on the base (today's command is `gh workflow run`), for example `l4 ci start`.
- Verifier resume per step (verifier 1.19): a stopped round starts over.
- Record in the ledger what a run dispatched (continuation, plan next run), so status needs no forge call to know.
- A concurrency design that keeps every working run serialised and still protects a pending continuation (for
  example a scheduled run on another ref that only relays, in a group of its own), if the extra job per tick proves
  cheaper than an occasional lost continuation.

## Open questions (each with the recommended answer)

Decided by the owner's delegate on 2026-10-20: every recommended answer below is taken (1 as written, 2 constants,
3 dispatch, 4 the template step with today's behaviour as the fallback, 5 L4-IMP ids with cross-references, 6 ask
the forge, best effort). The review then moved the relay before the configuration, which makes the check of question
1 a git-only read (D8).

1. Relay only when the base may have work (the brief, failing open), or always? Decided: as written. It follows the
   brief, saves runner minutes on idle ticks, and fails open on anything the running harness cannot read.
2. `MAX_STOPS = 2`, `FLOOR_S = 600` and the caps: constants or configuration keys? Decided: constants. The fix for a
   step that does not fit is a bigger job timeout, which is configured already.
3. A continuation when another unit of the run exits 11, 12 or 13: dispatch, or keep "exit 10 only" (L4-CI-004's
   wording today)? Decided: dispatch.
4. Job start through a template step (needs `l4 upgrade`), or by asking the API for the job's `started_at` at the
   start of `l4 run`? Decided: the template step; the fallback is today's behaviour plus one WARNING line.
5. Requirement ids: the relay and the status rule sit next to L4-ADO-005 and L4-YOLO-030, but the brief asked for
   L4-IMP-*. Decided: keep L4-IMP-072 to L4-IMP-074, with cross-reference sentences in L4-ADO-005 and L4-YOLO-030.
6. Ask the forge in `l4 yolo status`, or rely on age alone? Decided: ask, best effort, with a short timeout.
