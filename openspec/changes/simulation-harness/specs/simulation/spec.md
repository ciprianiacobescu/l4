## Purpose
Defines dry-run behaviour, the read-only planner `l4 plan`, and the scenario-driven simulation of the harness against fakes, including built-in scenarios and simulation with a repository's own configuration.

## ADDED Requirements

### Requirement: L4-SIM-001 (part a) Dry-run has no side effects
`--dry-run` for `run`, `verify` and `init` MUST perform every read and every decision but MUST NOT invoke agents or LLM backends, write to the repository, push, call forge write APIs, take locks or modify caches. Any attempted side effect MUST raise a `DryRunViolation`.

#### Scenario: SCN-DRY-01 (+) dry-run has zero side effects
- **GIVEN** a repo with actionable units
- **WHEN** `l4 run --dry-run`
- **THEN** git refs, working tree, forge (fake) and caches are unchanged; prompts exist under `.l4-out/dry-run/<run-id>/`; no agent or LLM process was spawned

#### Scenario: SCN-DRY-N3 (−) a side effect during dry-run is a bug, not an action
- **GIVEN** dry-run effects and code that attempts a git push, a forge write and a lock acquisition
- **WHEN** each is attempted
- **THEN** each raises `DryRunViolation`, nothing is executed, and the process exits 1

### Requirement: L4-SIM-001 (part b) Dry-run output
A dry-run MUST render every prompt to `.l4-out/dry-run/<run-id>/`, print every command it would execute with redacted environment, and end with a per-unit decision table and the exit code the real run would most likely return.

#### Scenario: SCN-DRY-N4 (+) rendered prompts, commands and decision table
- **GIVEN** one actionable unit and a fake adapter profile
- **WHEN** `l4 run --dry-run` runs
- **THEN** one prompt file exists per planned step, printed commands show `[REDACTED]` for secrets, and the last output lines are the decision table and `would exit 10`

### Requirement: L4-SIM-001 (part c) No probes unless asked
A dry-run MUST NOT run availability probes unless `--probe` is given; without it, selection MUST use cached probe results only and mark uncached profiles `unknown`.

#### Scenario: SCN-DRY-02 (−) dry-run does not probe unless asked
- **GIVEN** `l4 run --dry-run` without `--probe`
- **WHEN** it runs
- **THEN** selection uses cached probe results only and marks uncached profiles `unknown`

### Requirement: L4-SIM-001 (part d) Planner reports the next action per unit
`l4 plan` SHALL detect units and compute, without side effects, one `next_action` per unit from the lifecycle table, and emit with `--json` a document of schema `l4/plan@1` ordered by unit id; a unit is actionable exactly when its `next_action` requires a `run` job.

#### Scenario: SCN-DRY-N5 (+) plan lists actionable units deterministically
- **GIVEN** units `openspec:b` (pending tasks), `openspec:a` (all tasks done, no verdict) and `openspec:c` (merged)
- **WHEN** `l4 plan --json` runs twice
- **THEN** both outputs are byte-identical, ordered a, b, c, with `next_action` verify, implement and none, and two units actionable

#### Scenario: SCN-DRY-N6 (−) non-actionable phases are never scheduled
- **GIVEN** units in phases `rejected`, `halted`, `awaiting_human` without new answers, and `waiting_capacity` before `retry_after`
- **WHEN** `l4 plan --json` runs
- **THEN** none is actionable and each shows its reason

### Requirement: L4-SIM-001 (part e) Sweep adds duties
`l4 plan --sweep` SHALL add to the plan the sweeper duties of SPEC section 16.4: resume `waiting_capacity` units whose `retry_after` passed, resume expired leases, detect merged or closed PRs, refresh moved bases, honour `l4:resume`, re-run intake for changed `rejected` units, and repair mirrors. Each duty MUST be performed through an injected port.

#### Scenario: SCN-DRY-N7 (+) retry_after passed becomes a resume duty
- **GIVEN** a unit in `waiting_capacity` with `retry_after` one minute in the past
- **WHEN** `l4 plan --sweep --json` runs with a fake clock and fake forge
- **THEN** the plan holds a `resume` duty for the unit and plain `l4 plan` without `--sweep` does not

### Requirement: L4-SIM-002 (part a) Isolated remote and clone
`l4 simulate` MUST create a temporary bare repository acting as remote and a clone seeded from the scenario's built-in fixture repository, use real git, and touch only temporary directories, removing them unless `--keep` is given.

#### Scenario: SCN-SIM-N4 (+) temp dirs only
- **GIVEN** a scenario using fixture `openspec-basic`
- **WHEN** it is simulated, once without and once with `--keep`
- **THEN** no file outside the temporary directory changes, and the temporary directory exists only after the `--keep` run

### Requirement: L4-SIM-002 (part b) Scripted fakes
The runner MUST provide a fake agent adapter, fake LLM backend and in-memory fake forge (PRs, labels, statuses, dispatch queue), scripted per scenario by `steps` keyed on `when: {phase, task}`, and MUST run the real gate commands of the fixture, which use only the Python standard library.

#### Scenario: SCN-SIM-N5 (+) a scripted step writes files and returns a result
- **GIVEN** a step `when: {phase: red, task: "1.1"}` with `write` and `result: {status: done}`
- **WHEN** the fake adapter receives a matching request
- **THEN** it writes the named files from the fixture and returns the scripted result

#### Scenario: SCN-SIM-N6 (−) an unscripted request fails the scenario
- **GIVEN** a fake adapter with no step matching phase `green`, task `2.1`
- **WHEN** it receives that request
- **THEN** the scenario fails with a message naming the unmatched `when` and the scripted steps

### Requirement: L4-SIM-002 (part c) Scenario file format
A scenario file MUST validate against a model holding `name`, `fixture`, `config`, `profiles`, `judges`, `s1` and `expect`, with `@fixture:<file>` references resolved from the fixture directory; unknown keys and unresolved references are errors.

#### Scenario: SCN-SIM-N7 (−) malformed scenario is rejected before anything runs
- **GIVEN** a scenario with key `expct:` and another referencing `@fixture:missing.py`
- **WHEN** each is loaded
- **THEN** both fail naming the key or reference, and no temporary directory is created

### Requirement: L4-SIM-002 (part d) Expectation diff
The runner MUST compare `expect.exit_code`, `final_phase`, `events_include` and `trailers_include` with the run. On mismatch `l4 simulate` MUST exit 1 and print a diff of expected versus actual and the first diverging event.

#### Scenario: SCN-SIM-03 (−) expectation mismatch is reported precisely
- **GIVEN** a scenario expecting `final_phase: in_review` that ends in `escalated`
- **WHEN** simulated
- **THEN** exit 1 with a diff of expected vs actual phase and the first diverging event

### Requirement: L4-SIM-003 (part a) Built-in registry and determinism
The harness SHALL ship the built-in scenarios named in SPEC section 17 in a registry that `l4 simulate --all` runs, and given the same inputs two runs MUST produce identical event sequences once timestamps are removed.

#### Scenario: SCN-SIM-01 (+) built-in scenarios pass deterministically
- **GIVEN** the harness test suite
- **WHEN** `l4 simulate --all` runs twice
- **THEN** all pass and the event sequences (timestamps removed) are identical

### Requirement: L4-SIM-003 (part b) Pending scenarios are visible
A built-in scenario whose owning change has not landed MUST be reported as `pending` with its owner, never as passed, and a release check MUST fail while any built-in scenario is pending.

#### Scenario: SCN-SIM-N8 (−) pending is not pass
- **GIVEN** a registry entry `quota-fallback` with owner `agent-factory` and no runnable driver
- **WHEN** `l4 simulate --all --json` runs
- **THEN** it is listed with status `pending` and owner `agent-factory`, the summary line counts it as pending rather than passed, the exit code stays 0, and the release-gate test `test_no_pending_builtin_scenarios` (pytest marker `release`, deselected by default) fails

### Requirement: L4-SIM-003 (part c) Happy-path scenarios ship first
The scenarios `happy-openspec` and `happy-kiro` MUST be shipped as packaged scenario files with their fixtures and be runnable by name; each result MUST state which driver executed it (`orchestrator` or `skeleton`).

#### Scenario: SCN-SIM-N9 (+) a named scenario runs and names its driver
- **GIVEN** the packaged scenario `happy-openspec`
- **WHEN** `l4 simulate happy-openspec --json` runs
- **THEN** the result contains `driver` and `status`, and a red commit precedes the green commit in the event sequence

### Requirement: L4-SIM-004 (part a) Simulation with the repository's own configuration
`l4 simulate --all --with-repo-config` SHALL run the built-in scenarios against the repository's `.l4/config.yaml`, with adapters, backends and forge swapped for fakes, validating chains, gate wiring and CI rendering without spending tokens.

#### Scenario: SCN-SIM-02 (+) user-config simulation
- **GIVEN** a target repo with its own config
- **WHEN** `l4 simulate --all --with-repo-config`
- **THEN** scenarios run with fakes and the repo's chains/gates; no tokens are spent

### Requirement: L4-SIM-004 (part b) No real agent is ever executed
With `--with-repo-config` the runner MUST replace every adapter and backend by fakes before the first step and MUST fail the run if any real agent binary or network call would be made.

#### Scenario: SCN-SIM-N10 (−) real adapters in the repo config are swapped out
- **GIVEN** a repo config whose profiles name `codex` and `claude-code` adapters and real API keys in the environment
- **WHEN** `l4 simulate --all --with-repo-config` runs with a spy on process spawning and sockets
- **THEN** no agent binary is spawned and no connection is opened

#### Scenario: SCN-SIM-N11 (−) an invalid repo config stops the simulation early
- **GIVEN** a repo config with a role chain naming an undefined profile
- **WHEN** `l4 simulate --all --with-repo-config` runs
- **THEN** it exits 2 naming the chain path before any scenario starts
