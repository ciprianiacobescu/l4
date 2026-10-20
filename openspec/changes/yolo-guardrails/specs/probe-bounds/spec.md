## Purpose

An availability probe ends in bounded time, whatever the CLI leaves running. When it ends without an answer, the
reason names the CLI and what to run.

## ADDED Requirements

### Requirement: L4-AVL-012 Probe steps are bounded and a timeout is named
Every subprocess of an availability probe (the `binary`, `auth`, `quota` and `hello` steps) SHALL run in its own
process group. Its output SHALL be read until the direct child has exited and both pipes are closed, or until a grace
of 2 seconds after the child's exit, whichever comes first. The read MUST NOT wait for a process that still holds a
pipe after that grace, inside or outside the group. A child that exited before the timeout MUST NOT be reported as timed out: its return code and the output read so far are returned, the grace ending at the timeout when that comes first. At the grace or the timeout, the harness MUST kill the whole group.
The `binary`, `auth` and `quota` steps SHALL use `availability.probe_step_timeout` (default `20s`, capped by
`availability.probe_timeout`), and the `hello` SHALL keep `availability.probe_timeout`. A step that does not answer in
time MUST fail as `transient` with the reason `<cli> did not answer within <N> s (<step> step); <cause>: run l4
doctor`, where `<cause>` names an OpenCode v2 daemon or a login prompt for `opencode`, and a login prompt or a helper
process for any other CLI. An agent run (`ProcRunner`) MUST end within a bounded time after its kill, even when a
process outside its group holds its output.

#### Scenario: SCN-AVL-21 (−) A helper in its own session that holds the output does not hang a probe
- **GIVEN** a CLI that prints `1.18.34`, starts a helper in a new session that inherits stdout and sleeps 60 s, and
  exits 0
- **WHEN** `l4.proc.run_process` runs it with a 10 s timeout
- **THEN** it returns within 4 s with exit code 0 and stdout `1.18.34\n`

#### Scenario: SCN-AVL-22 (−) A step that does not answer is named and its group is killed
- **GIVEN** an `opencode` whose `auth list` never answers and that has a child in the same group
- **WHEN** the `auth` step runs with `probe_step_timeout: 2s`
- **THEN** it fails within about 2 s plus the grace, as `transient`, with the reason `opencode did not answer within
  2 s (auth step); an OpenCode v2 daemon or a login prompt can cause this: run l4 doctor`, and no process of that
  group is left

#### Scenario: SCN-AVL-23 (−) A hello that does not answer names the CLI
- **GIVEN** a `claude` hello that does not answer within `probe_timeout`
- **WHEN** the `hello` step runs
- **THEN** it fails as `transient` with the reason `claude did not answer within <N> s (hello step); a login prompt or
  a helper process that keeps the output open can cause this: run l4 doctor`

#### Scenario: SCN-AVL-24 (−) An agent run whose escaped helper holds its output ends
- **GIVEN** an agent process that starts a helper in a new session that holds its stdout, and then exits
- **WHEN** `ProcRunner.run` runs it
- **THEN** it returns the outcome within the join bounds and logs `a process outside the agent's process group still
  holds its output: the raw events end here`

#### Scenario: SCN-AVL-25 (+) The step timeout reaches every non-hello step
- **GIVEN** `availability.probe_step_timeout: 5s` and `availability.probe_timeout: 60s`, and in a second case
  `probe_step_timeout: 90s`
- **WHEN** the `binary`, `auth` and `quota` steps of the claude, codex, opencode and kiro-cli probes run against a fake
  runner that records the timeout it is given
- **THEN** every non-hello call gets 5 s and the hello gets 60 s; in the second case every call gets at most 60 s
