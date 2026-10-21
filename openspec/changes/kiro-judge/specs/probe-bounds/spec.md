## Purpose

An availability probe ends in bounded time, and a CLI whose normal answer is slow still passes its probe without
configuration. kiro-cli's quota call and model listing take 23 to 30 s on a hosted runner, so L4-AVL-012 (0.4.18,
`yolo-guardrails`) gains an adapter floor and a recorded duration. SPEC.md keeps the full text of the modified
requirement; the block below states what it says once this change is made.

## MODIFIED Requirements

### Requirement: L4-AVL-012 Probe steps are bounded and a timeout is named
Every subprocess of an availability probe (the `binary`, `auth`, `quota` and `hello` steps) SHALL run in its own
process group. Its output SHALL be read until the direct child has exited and both pipes are closed, or until a grace
of 2 seconds after the child's exit, whichever comes first. The read MUST NOT wait for a process that still holds a
pipe after that grace, inside or outside the group. A child that exited before the timeout MUST NOT be reported as
timed out: its return code and the output read so far are returned, the grace ending at the timeout when that comes
first. At the grace or the timeout, the harness MUST kill the whole group. The `binary`, `auth` and `quota` steps
SHALL use `availability.probe_step_timeout` (default `20s`), and the `hello` SHALL keep `availability.probe_timeout`.
An adapter MAY declare a longer floor for a slow call of its own: the `kiro-cli chat --no-interactive /usage` call of
the `quota` step and the `kiro-cli chat --list-models` call of the `auth` step declare 90 s, and run for the longer of
the step timeout and that floor; the `binary` step and `kiro-cli whoami` keep the step timeout. Every step timeout, a
floor included, is capped by `availability.probe_timeout` (default `60s`, so the kiro-cli floor is 60 s under the
defaults). Every probe step SHALL record how long it ran as `step_ms` in its result, and a step of 1 s or more SHALL
show that time in the `l4 probe` line, in `probes.<profile>.step_ms` of `availability.selected` and in the `l4 doctor`
LIVE-001 line. A step that does not answer in time MUST fail as `transient` with the reason `<cli> did not answer
within <N> s (<step> step); <cause>: run l4 doctor`, where `<N>` is the seconds actually used and `<cause>` names an
OpenCode v2 daemon or a login prompt for `opencode`, and a login prompt or a helper process for any other CLI. An agent
run (`ProcRunner`) MUST end within a bounded time after its kill, even when a process outside its group holds its
output.

#### Scenario: SCN-AVL-26 (+) A kiro-cli quota step of 30 s passes under the default configuration
- **GIVEN** the default `probe_step_timeout: 20s` and `probe_timeout: 60s`, and a `kiro-cli chat --no-interactive
  /usage` that answers after 30 s
- **WHEN** the `quota` step runs
- **THEN** the call runs with a 60 s timeout, the step passes, and its result records `step_ms` 30000

#### Scenario: SCN-AVL-27 (−) A kiro-cli step over the floor times out naming the seconds used
- **GIVEN** a `kiro-cli` whose `/usage` never answers, and `probe_timeout` of 60 s (then 120 s)
- **WHEN** the `quota` step runs
- **THEN** it fails as `transient` with the reason `kiro-cli did not answer within 60 s (quota step); a login prompt or
  a helper process that keeps the output open can cause this: run l4 doctor` (with 120 s: `within 90 s`)
