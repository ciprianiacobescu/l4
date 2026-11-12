## Context

`agent_step` (`src/l4/implementer/tdd.py`) sets `stall_timeout_s=float(idle_s)` from `implementer.idle_timeout` and
passes an `ActivityWatch`. `ProcessRunner._wait` (`src/l4/agents/proc.py`) stops the run when no line came for
`stall_timeout_s` and `watch.has_open_call()` is false, and records `watch.stopped_idle_s`. After the run, `agent_step`
emits `agent.idle{task, phase, attempt, profile, silent_s, tool_calls, silent, reason?}` and fails the attempt with
`the agent showed no activity for <idle_timeout> (implementer.idle_timeout), so L4 stopped it`, or raises the silent
limit (`LimitSignal(..., "silent", ..., "run.idle", "no output for <idle_timeout>")`, L4-IMP-087).
`_previous_attempt_block` says `went silent: no output for <idle_timeout>`; `progress.py` prints the `agent.idle` line.

Readers: `claude_code_signals`, `codex_signals`, `kiro_signals`, `copilot_signals` emit `start`/`end` with call ids,
so a long tool call is open. `opencode_signals` emits only `call` (on a finished `tool_use`); `command.py` passes
`reader=None`.

Every gate run goes through `Workbench.run_gate_spec`, and `GateResult.seconds` holds its command's wall time
(L4-IMP-097). Before an implementer step the harness has run, in this unit run, the test gate at the base (`baseline`)
and the static baselines (`lint-baseline`, `typecheck-baseline`), unless the baseline was reused (L4-IMP-088), in which
case the test gate of the previous green step of the same run was timed.

The step's wall-clock limit is `RunRequest.timeout_s` (1800 s).

## Goals / Non-Goals

**Goals:** an opencode agent that runs the test gate (or a lint or typecheck command) is not stopped as idle while the
command runs; a hung opencode run is still stopped, later.

**Non-Goals:** a process-tree or CPU check of the agent's children; reading OpenCode's step bracket as an open call
(see the proposal); changing the idle limit of claude-code, codex, kiro-cli or copilot-cli; a configuration key; a
doctor warning.

## Decisions

### D1. Which adapters

`AgentCaps` gains `open_calls: bool = True`: whether the adapter's stream reader shows a tool call as open while it
runs. opencode (1.x), opencode 2 and the command adapter return `open_calls=False`. The fake adapter keeps the default
(tests that need the floor pass `open_calls=False` through the fake's caps, or monkeypatch).

### D2. What is measured

`Workbench` keeps `gate_peak: tuple[str, float] | None`, the name and wall time of the longest run, in this unit run,
of a command the implementer may run, on the work tree as it is: a gate named `baseline` or `test` whose command is
`gates.test.command`, and a gate named `lint`, `lint-baseline`, `typecheck` or `typecheck-baseline` (the names
`run_static_gates` gives) whose command is a `gates.lint` or `gates.typecheck` command. `run_gate_spec` updates it after
each such gate whose `seconds` is above 0 and that neither timed out nor was stopped by the soft deadline
(`timed_out`, `deadline`). Variant runs (`test-base-run`, the zero-value run, `test-at-red`, `test-extra-base`) are not
counted: they run the code varied or at the base, and a base run that hangs to its limit would raise the floor to the
step's limit. `setup`, `build`, `e2e` and the serve command are not counted (the implementer is not told to run them).

### D3. The limit

In `agent_step`, with `idle_s` from `implementer.idle_timeout`:

```
limit_s = idle_s
if idle_s and not wb.impl.capabilities().open_calls and wb.gate_peak:
    floor = ceil(IDLE_FLOOR_FACTOR * peak_seconds) + IDLE_FLOOR_MARGIN_S   # 1.5, 60
    limit_s = min(max(idle_s, floor), request_timeout_s)
```

`stall_timeout_s=float(limit_s)`. `IDLE_FLOOR_FACTOR = 1.5` and `IDLE_FLOOR_MARGIN_S = 60` are module constants with a
comment: the agent's own run of the command, in its sandbox and under the runner's load, can take longer than the
harness's. `idle_s == 0` keeps the watchdog off.

### D4. What is recorded and said

- `agent.idle` gains `limit_s` (always, the limit that applied) and `raised_by{gate, seconds}` (only when `limit_s` is
  above `idle_s`; `seconds` rounded to a whole second).
- The failed attempt's reason, when raised: `the agent showed no activity for <ago(limit_s)> (implementer.idle_timeout
  <idle_timeout>, raised to the longest gate run of this run plus a margin, because <adapter> shows no open tool call),
  so L4 stopped it`, with `<adapter>` the profile's adapter name. Not raised: today's text.
- The silent limit's text and `_previous_attempt_block` use `no output for <ago(limit_s)>` when raised.
- `progress.py`'s `agent.idle` line: when `raised_by` is present, `(implementer.idle_timeout, raised to <ago(limit_s)>
  for the longest gate run)` in place of `(implementer.idle_timeout)`.

### D5. L4-IMP-087

The silent stop is unchanged in kind (no tool call, more than one implementer profile): it fires at `limit_s`. The
named risk in the SPEC is reworded.

## Risks / Trade-offs

- A hung opencode run is stopped later: with a 6-minute test gate, after about 10 minutes instead of 5. With a gate of
  more than about 19 minutes the floor reaches the step's limit and the idle stop no longer fires for opencode; the step
  limit still does.
- An agent that runs a long command other than a gate (a dev server, an e2e run) is still stopped at the raised limit.
- The first step of a run whose baseline was reused from nothing measured has no floor; today's limit applies.
