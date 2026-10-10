## Purpose
Defines the operational design domain checks run at intake and before every run, the test-oracle bootstrap unit, the adoption of finished-but-unverified work, and the deterministic gate runner with timeouts, logs and non-vacuous test judgement.

## ADDED Requirements

### Requirement: L4-ODD-001 Intake checks reject with every failure listed (part a)
At intake, and again before every run of a unit, the harness SHALL evaluate all four ODD checks and, if any fail, reject the unit with exit 14 and one `unit.rejected` event listing every failed check. A rejected unit whose spec or config is corrected SHALL be re-admitted to `ready`.

#### Scenario: SCN-ODD-04 (+) Fixing the spec re-admits the unit
- **GIVEN** a rejected unit
- **WHEN** a human pushes a corrected spec
- **THEN** the next run's intake passes, phase `ready`, the rejection comment is resolved in the sticky comment

#### Scenario: SCN-ODD-N1 (−) Two failures are both reported
- **GIVEN** a unit that has no criteria and lists a forbidden path in its Impact section
- **WHEN** intake runs
- **THEN** one `unit.rejected` event lists both reasons and the exit code is 14

### Requirement: L4-ODD-001 Strict validation and SDD criteria (part b)
Intake SHALL require that the unit validates strictly and, under `sdd.enforce`, has at least one criterion and every non-exempt leaf task mapped to at least one criterion (Kiro: `_Requirements:_`; OpenSpec: scenarios exist, task mapping advisory).

#### Scenario: SCN-ODD-01 (−) No criteria under SDD
- **GIVEN** an OpenSpec change whose deltas contain requirements without scenarios (`skip_specs` absent)
- **WHEN** intake runs
- **THEN** `openspec validate --strict` fails → unit `rejected`, exit 14, `unit.rejected.reasons` lists the validator issues; PR (if any) gets a comment; no agent call

#### Scenario: SCN-ODD-02 (−) Kiro leaf without requirement reference
- **GIVEN** leaf `3.1 Add cache` without `_Requirements:_` and not tagged `[chore]`
- **WHEN** intake runs
- **THEN** rejected (14) with reason `task 3.1 cites no requirement`

### Requirement: L4-ODD-001 Test oracle required (part c)
Under `tdd.mode != off` and `odd.require_test_oracle`, intake SHALL require `gates.test.command` to be configured and runnable, and MUST reject the unit otherwise with reason `test oracle missing`.

#### Scenario: SCN-ODD-N2 (−) Configured test command that cannot run
- **GIVEN** `gates.test.command: "uv run pytest"` and a runner where `uv` is not installed
- **WHEN** intake runs
- **THEN** the unit is rejected (14) with reason `test oracle not runnable: uv`

### Requirement: L4-ODD-001 Forbidden paths (part d)
Intake SHALL reject a unit whose declared paths (Impact sections of design and proposal, task file references) intersect `odd.forbidden_paths`, naming the path and the matching glob.

#### Scenario: SCN-ODD-03 (−) Forbidden path in scope
- **GIVEN** a design that lists `db/migrations/0042_add_users.sql` under Impact and `odd.forbidden_paths` includes `**/migrations/**`
- **WHEN** intake runs
- **THEN** rejected (14) naming the path and the matching glob

### Requirement: L4-ODD-002 Bootstrap unit creation (part a)
When the only failed intake check is the missing test oracle and `odd.bootstrap_tests: true`, the harness SHALL create, once per repository, the unit `l4-bootstrap-tests` in the primary framework, and other units SHALL stay `rejected` with reason `waiting for test bootstrap`.

#### Scenario: SCN-ODD-05 (+) Missing oracle bootstraps tests instead of dead-ending
- **GIVEN** a web repo (`package.json` with a web framework) without any test runner, `odd.bootstrap_tests: true`
- **WHEN** intake runs for `openspec:add-login`
- **THEN** `add-login` is `rejected` with `waiting for test bootstrap`; a unit `l4-bootstrap-tests` is created once (exempt from the branch-spec refusal), with `[test-infra]` tasks; it is verified with the gates from its own `.l4/proposed-gates.yaml`, run in the gate sandbox; after a human merges it and adopts the gates, the sweeper re-admits `add-login`

#### Scenario: SCN-ODD-N3 (−) The bootstrap unit is not created twice
- **GIVEN** an existing `l4-bootstrap-tests` unit and another unit failing the oracle check
- **WHEN** intake runs again
- **THEN** no second bootstrap unit is created

### Requirement: L4-ODD-002 Bootstrap content (part b)
The bootstrap unit's tasks SHALL be tagged `[test-infra]` by the harness and add a test runner with machine-readable reports, one smoke test, Playwright with one smoke page test when a web UI is detected, and a proposed gates block in `proposed-gates.yaml` inside the unit's own folder.

#### Scenario: SCN-ODD-N4 (+) Web UI adds a Playwright smoke task
- **GIVEN** a repo whose `package.json` lists a web framework
- **WHEN** the bootstrap unit is planned
- **THEN** its tasks include a Playwright smoke page test and all tasks carry `[test-infra]`

### Requirement: L4-ODD-002 Bootstrap verification and review (part c)
The bootstrap unit SHALL skip ODD check 3 and be verified with the gates from its own `proposed-gates.yaml`, always inside the credential-free gate sandbox, and its PR body MUST state "gates self-proposed — review them before adopting".

#### Scenario: SCN-ODD-07 (−) Gate commands proposed on a branch never run with secrets
- **GIVEN** `l4-bootstrap-tests` whose `.l4/proposed-gates.yaml` contains `curl $L4_FORGE_TOKEN …`
- **WHEN** the bootstrap unit is verified
- **THEN** the command runs in the gate sandbox, where `L4_FORGE_TOKEN` is not set and no credential is readable

### Requirement: L4-ODD-002 Gates are adopted only by a human (part d)
Configuration SHALL stay human-owned: the harness MUST NOT copy proposed gates into `.l4/config.yaml`, and the sweeper SHALL re-run intake only after a human has merged the bootstrap PR and adopted the gates.

#### Scenario: SCN-ODD-N5 (−) Proposed gates are not auto-adopted
- **GIVEN** a merged bootstrap PR whose `proposed-gates.yaml` is not yet in `.l4/config.yaml`
- **WHEN** the sweeper runs
- **THEN** other units remain `rejected` with `waiting for test bootstrap` and `.l4/config.yaml` is unchanged

### Requirement: L4-ODD-003 Adoption of finished work
With `odd.verify_preexisting: true`, a unit whose non-optional tasks are all `[x]` but which has no recorded PASS SHALL enter at `implemented` and be verified; tasks completed before the unit's first ledger event are `pre_adoption` and exempt only from the TDD-history check.

#### Scenario: SCN-ODD-06 (+) Finished-but-unverified work is verified, not skipped
- **GIVEN** a change whose tasks were all ticked `[x]` before the harness was adopted, with no ledger
- **WHEN** the router plans
- **THEN** the unit enters `implemented` → `verifying`; its tasks are reported `pre_adoption`; the TDD-history check is not applied to them; every other check is

#### Scenario: SCN-ODD-N6 (−) Adoption disabled skips the unit
- **GIVEN** `odd.verify_preexisting: false` and an all-`[x]` unit without a PASS record
- **WHEN** the router plans
- **THEN** the unit is not entered into the lifecycle and no verification is started

### Requirement: L4-GAT-001 Gate execution with timeout and logs (part a)
Gate commands SHALL run with the timeout `gates.timeout`, capturing stdout and stderr to `.l4-out/gates/<run-id>/<gate>.log`, and on timeout the harness MUST kill the whole process group and fail the gate with reason `timeout` while keeping the log.

#### Scenario: SCN-GAT-03 (−) Gate timeout
- **GIVEN** a test command that hangs
- **WHEN** `gates.timeout` (30 m) elapses
- **THEN** the process group is killed, the gate fails with `timeout`, the log is kept

### Requirement: L4-GAT-001 Gate judgement by exit code and report (part b)
A gate SHALL be judged by its exit code and, for test gates, by the parsed report; a non-zero exit code MUST fail the gate whatever the report says.

#### Scenario: SCN-GAT-N1 (−) Non-zero exit with a green report still fails
- **GIVEN** a test command that exits 1 after writing a JUnit report with no failures
- **WHEN** the gate is judged
- **THEN** the gate fails with reason `exit code 1`

### Requirement: L4-GAT-002 Non-vacuous test gates
A test gate SHALL fail when zero tests executed, when its report file is missing, or when the report does not contain the tests the step is about; it MUST NOT report a pass in those cases.

#### Scenario: SCN-GAT-01 (−) Vacuous test gate
- **GIVEN** `gates.test.command` exits 0 but the JUnit report has `tests="0"`
- **WHEN** a gate runs
- **THEN** the gate fails with reason `vacuous: 0 tests executed`

#### Scenario: SCN-GAT-02 (−) Missing report
- **GIVEN** the test command exits 0 but writes no report file
- **WHEN** a gate runs
- **THEN** the gate fails with `report missing: .l4-out/junit.xml`

### Requirement: L4-GAT-003 Gate proposal from ecosystem markers
`l4 init` SHALL propose gate commands from ecosystem markers (`pyproject.toml` or `uv.lock`: uv and pytest with `--junitxml`; `package.json` scripts and lockfile; `go.mod`; `Cargo.toml`) and MUST leave a `TODO` comment where it cannot propose one.

#### Scenario: SCN-GAT-N2 (+) Python repository gets a uv and pytest proposal
- **GIVEN** a repository containing `pyproject.toml` and `uv.lock`
- **WHEN** gates are proposed
- **THEN** the proposed test command is `uv run pytest --junitxml=.l4-out/junit.xml` with report `.l4-out/junit.xml`

#### Scenario: SCN-GAT-N3 (−) Unknown ecosystem leaves a TODO
- **GIVEN** a repository with no recognised ecosystem marker
- **WHEN** gates are proposed
- **THEN** the proposal has an empty test command with a `TODO` comment and no invented command
