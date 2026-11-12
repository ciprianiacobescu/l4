## ADDED Requirements

### Requirement: L4-IMP-099 The idle stop of an agent whose stream shows no open tool call waits for the longest gate run
For an implementer step on an adapter whose stream reader cannot show a tool call as open while it runs (opencode 1.x
and 2.x, which write a tool call only when it ends, and an adapter with no stream reader), the idle limit SHALL be the
larger of `implementer.idle_timeout` and 1.5 times the longest wall time of a gate run the harness made earlier in the
same unit run of a command the implementer may run on the work tree as it is (a `baseline` or `test` run of
`gates.test.command`, and the runs of `gates.lint` and `gates.typecheck` commands, their baselines included), plus 60
seconds, rounded up to a whole second, and at most the step's wall-clock limit; the cap SHALL never lower the limit
below `implementer.idle_timeout`, so the limit is the larger of `implementer.idle_timeout` and the smaller of that floor
and the step's limit. A gate run that timed out or that the
soft deadline stopped, and a variant run (`test-base-run`, the zero-value run, `test-at-red`, `test-extra-base`) SHALL
NOT count. With no such run measured, or with `implementer.idle_timeout: 0`, the limit SHALL be as before. An adapter
whose reader shows open calls (claude-code, codex, kiro-cli, copilot-cli) SHALL keep `implementer.idle_timeout`.

`agent.idle` SHALL carry `limit_s`, the limit that applied, and, when it is above `implementer.idle_timeout`,
`raised_by{gate, seconds}` (the name and whole seconds of the longest run). The failed attempt's reason SHALL then read
`the agent showed no activity for <limit> (implementer.idle_timeout <idle_timeout>, raised to the longest gate run of
this run plus a margin, because <adapter> shows no open tool call), so L4 stopped it`, and the progress line SHALL name
the raised limit. A silent stop (L4-IMP-087) SHALL use the same limit, and its texts SHALL name it.

#### Scenario: SCN-IMP-537 (+) An opencode step's idle limit is raised to the measured gate run
- **Given** `implementer.idle_timeout: 5m`, a `baseline` run of the test gate of 381 s, a `lint-baseline` run of 15 s
  and a `typecheck-baseline` run of 16 s in this unit run, and an opencode implementer profile
- **When** the implementer step starts
- **Then** its idle limit is 632 s (1.5 × 381, plus 60, rounded up); a claude-code step in the same run has 300 s

#### Scenario: SCN-IMP-538 (−) An opencode agent silent beyond the raised limit is stopped and told why
- **Given** the step of SCN-IMP-537, whose agent made tool calls and then printed nothing for 632 s
- **When** the watchdog stops it
- **Then** `agent.idle` holds `limit_s: 632`, `raised_by: {gate: "baseline", seconds: 381}` and `silent: false`, and the
  attempt fails with `the agent showed no activity for 10m (implementer.idle_timeout 5m, raised to the longest gate run
  of this run plus a margin, because opencode shows no open tool call), so L4 stopped it`

#### Scenario: SCN-IMP-539 (+) Without a measured run, with the watchdog off, or above the step limit, the limit is bounded
- **Given** an opencode step with no counted gate run yet (or only a `test-base-run` of 1800 s, or a `baseline` that
  timed out), a step with `implementer.idle_timeout: 0`, a step after a `baseline` run of 1400 s, and a step with
  `implementer.idle_timeout: 40m` after a `baseline` run of 1400 s
- **When** each step starts
- **Then** the first has the limit `implementer.idle_timeout`, the second has no idle stop, the third has the step's
  wall-clock limit (1800 s), not 2160 s, and the fourth keeps 2400 s (the cap never lowers the limit below
  `implementer.idle_timeout`; no `raised_by`)

#### Scenario: SCN-IMP-540 (+) A silent stop waits for the raised limit
- **Given** two implementer profiles, the first on opencode, the run of SCN-IMP-537, and an agent that makes no tool call
- **When** it prints nothing
- **Then** it is stopped after 632 s, not 300 s, with `agent.idle{silent: true, limit_s: 632}`, and the step is a limit
  of the profile (`no output for 10m`), not a failed attempt

## MODIFIED Requirements

### Requirement: L4-IMP-024 (amendment, the idle limit)
An implementer agent SHALL be idle when its stdout has had no line for its idle limit and its stream reader (L4-FAC-012)
shows no open tool call. The idle limit SHALL be `implementer.idle_timeout`, raised for an adapter whose reader cannot
show an open call as L4-IMP-099 says. The rest of L4-IMP-024 is unchanged.

#### Scenario: SCN-IMP-538 is the scenario of this amendment (see above)
- **Given** the step of SCN-IMP-537
- **When** the agent prints nothing for 632 s
- **Then** it is stopped then, not after 300 s

### Requirement: L4-IMP-087 (amendment, the named risk)
The named risk SHALL read: an agent whose first tool call runs, or which thinks, for longer than its idle limit with
nothing printed reads as silent; OpenCode (1.x and 2.x share the stream reader) reports a tool call only when the call
ends, so a first call longer than its idle limit (L4-IMP-099: at least the longest counted gate run of the unit run, times
1.5, plus 60 s) reads as silent there, at the cost of one cool-down of that profile and a move, at most once per task.

#### Scenario: SCN-IMP-540 is the scenario of this amendment (see above)
- **Given** the run of SCN-IMP-540
- **When** the agent prints nothing
- **Then** the silent stop comes at the raised limit
