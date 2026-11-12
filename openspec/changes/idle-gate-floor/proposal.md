## Why

In a consumer's TypeScript repository (`implementer.idle_timeout: 5m`) the test gate took 6m21s at the base and about
6m20s at head. Its free implementer profiles run on opencode. In a fix task, three of four free attempts were stopped as
idle after 98, 51 and 11 tool calls (`agent.idle{silent_s: 300, silent: false}`); in an earlier unit's run all four free
attempts of a task ended the same way. Each such halt spent two to four attempts before the task reached a paid profile.

The idle watchdog (L4-IMP-024) stops an agent whose stdout has had no line for `implementer.idle_timeout` while its
stream reader shows no open tool call. OpenCode (1.x and 2.x share the reader, `activity.opencode_signals`) writes a
tool call only when the call ends (`tool_use` with state `completed` or `error`; the recorded fixtures hold no other),
so a tool call is never open there (`test_opencode_stream_never_has_an_open_call` pins it). An agent that runs the test
gate, the one command every implementer is told to run, prints nothing for as long as the gate runs; when that is longer
than `implementer.idle_timeout`, L4 stops it as idle. Which command ran at each of those stops is not recorded [I]; the
mechanism is [V].

L4-IMP-087 already names this as an accepted risk for an agent's first call ("OpenCode ... reports a tool call only when
the call ends, so a first call longer than `idle_timeout` reads as silent there"). It also holds for every later call,
where the stop is a failed attempt.

The step bracket of OpenCode's stream (`step_start` ... `step_finish`) cannot stand in for an open call: `step_start` is
written before the model is called, and a step whose model call fails is followed by another `step_start` with no
`step_finish` (the recorded `error-upstream-503` stream). Treating a step as an open call would let a hung model call run
to the 30-minute step limit, and the silent stop of L4-IMP-087 would never fire.

## What Changes

- For an adapter whose stream reader cannot show an open call (opencode 1.x and 2.x; an adapter with no stream reader),
  the idle limit of an implementer step is the larger of `implementer.idle_timeout` and 1.5 times the longest wall time
  of a test, lint or typecheck gate run the harness made earlier in the same unit run (the baselines included), plus 60
  seconds; at most the step's wall-clock limit. With nothing measured, the limit is `implementer.idle_timeout`.
- claude-code, codex, kiro-cli and copilot-cli keep `implementer.idle_timeout` (their readers show open calls).
- `agent.idle` gains `limit_s` and, when raised, `raised_by{gate, seconds}`; the attempt's reason and the progress line
  name the raised limit. A silent stop (L4-IMP-087) uses the same limit.
- `AgentCaps` gains `open_calls` (True by default; False for opencode, opencode 2 and the command adapter).
- L4-IMP-087's named risk is reworded: a first call longer than the raised limit still reads as silent there.

## Capabilities

### New Capabilities

- `idle-gate-floor`: L4-IMP-099, the idle stop of an agent whose stream shows no open tool call waits for the longest
  gate run.

### Modified Capabilities

- L4-IMP-024 (the idle limit), L4-IMP-087 (the named risk).

## Impact

- `src/l4/agents/base.py` (`AgentCaps.open_calls`), `src/l4/agents/opencode.py`, `src/l4/agents/opencode_v2.py`,
  `src/l4/agents/command.py`, `src/l4/implementer/workbench.py` (the longest gate run of the unit run),
  `src/l4/implementer/tdd.py` (`agent_step`), `src/l4/progress.py` (the `agent.idle` line).
- `docs/SPEC.md` (L4-IMP-099, L4-IMP-024, L4-IMP-087, SCN-IMP-537..540, change-table row 129), `CHANGELOG.md`.
- No configuration key changes. `agent.idle` gains two optional fields.
