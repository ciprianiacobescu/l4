## Purpose
Defines the doctor framework: a registry of identified checks with severities, the table and JSON reports, exit semantics, scope flags, safe fixes, and the environment and configuration checks delivered by this change.

## ADDED Requirements

### Requirement: L4-DOC-001 (part a) Table, JSON and exit code
`l4 doctor` SHALL run the registered checks, print a table with columns `id, severity, status, message, fix`, and with `--json` print a document of schema `l4/doctor@1`. It MUST exit 3 if any check of severity `error` has status `fail`, and 0 otherwise.

#### Scenario: SCN-DOC-01 (+) healthy repository
- **GIVEN** a correctly configured repo
- **WHEN** `l4 doctor`
- **THEN** every check passes or is `info`; exit 0; `--json` validates against its schema

#### Scenario: SCN-DOC-N5 (−) a failing error check fails the run
- **GIVEN** a registered check of severity `error` that fails and one of severity `warn` that fails
- **WHEN** `l4 doctor --json` runs
- **THEN** exit 3, both checks appear with status `fail`, and removing the error check makes the exit code 0

### Requirement: L4-DOC-001 (part b) Check registry is extensible
Checks SHALL be declared as objects with an `id`, a severity (or a severity function of the configuration), scopes, a run function and an optional fix, collected in a registry that other changes extend. A duplicate id MUST be rejected at registration.

#### Scenario: SCN-DOC-N6 (+) another change adds a check and a severity downgrade
- **GIVEN** a check registered with severity `error` that is downgraded to `warn` when `ci.platform` is `local`
- **WHEN** doctor runs with `ci.platform: local` and then `github`
- **THEN** the same failing check is reported as `warn` then `error`

#### Scenario: SCN-DOC-N7 (−) duplicate check id is refused
- **GIVEN** a registry already holding `ENV-001`
- **WHEN** a second check with id `ENV-001` is registered
- **THEN** registration raises an error naming the id

### Requirement: L4-DOC-001 (part c) CI and unit scope
With `--ci` doctor MUST run only checks that declare the `ci` scope; without it, every non-live check. With `--unit ID` checks that take a unit MUST be restricted to that unit and unit-independent checks run once.

#### Scenario: SCN-DOC-N8 (+) scope flags select checks
- **GIVEN** one check scoped `ci`+`local`, one scoped `local` only, and one unit-aware check
- **WHEN** doctor runs with `--ci`, then without it, then with `--unit openspec:a`
- **THEN** the first run omits the local-only check, the second includes all, and the third runs the unit-aware check for `openspec:a` only

### Requirement: L4-DOC-001 (part d) Live checks are opt-in
`--live` SHALL add the checks with ids `LIVE-*`; they MUST NOT run otherwise. Live probe cost MUST be summed and reported in the table footer and the JSON.

#### Scenario: SCN-DOC-04 (+) live probes
- **GIVEN** `l4 doctor --live`
- **WHEN** it runs
- **THEN** each required chain's first profile is hello-probed; total probe cost is reported; MCP and S1 smoke results are listed

### Requirement: L4-DOC-001 (part e) Fix applies only safe, listed fixes
`--fix` SHALL apply only fixes registered as safe by a check (prune, release, delete, create, rebuild mirrors, re-render, and the user-local tool installs of L4-PRV-004/005), and doctor MUST verify afterwards that no tracked file changed, failing with exit 1 if one did. With `--ci`, only provisioning fixes SHALL run.

#### Scenario: SCN-DOC-03 (+) `--fix` is safe
- **GIVEN** stale worktrees, an expired lease, missing labels
- **WHEN** `l4 doctor --fix`
- **THEN** worktrees pruned, lease released, labels created; no spec file, `tasks.md`, `questions.md` or lesson is modified (`git diff` of tracked files empty)

#### Scenario: SCN-DOC-N9 (−) a fix that edits a tracked file is caught
- **GIVEN** a registered fix that rewrites `openspec/changes/x/tasks.md`
- **WHEN** `l4 doctor --fix` runs
- **THEN** exit 1 with a message naming the modified file

### Requirement: L4-DOC-001 (part f) ENV-001 to ENV-003 toolchain checks
Doctor MUST provide ENV-001 (error: Python 3.11 or newer and `uv` present), ENV-002 (error: git 2.40 or newer) and ENV-003 (error: Node 20.19 or newer and the pinned OpenSpec CLI runnable, only when OpenSpec is active by `spec.frameworks` or an existing `spec.openspec.root` directory).

#### Scenario: SCN-DOC-N10 (+) toolchain present
- **GIVEN** git 2.43, uv, Python 3.12, Node 20.19.0 and the pinned OpenSpec on the path
- **WHEN** `l4 doctor` runs
- **THEN** ENV-001, ENV-002 and ENV-003 pass

#### Scenario: SCN-DOC-N11 (−) old git and absent OpenSpec
- **GIVEN** git 2.39, and OpenSpec active but not installed in `$L4_CACHE/tools`
- **WHEN** `l4 doctor` runs
- **THEN** ENV-002 and ENV-003 fail with severity error and exit 3; ENV-003 is skipped when OpenSpec is not active

### Requirement: L4-DOC-001 (part g) ENV-004 adapter binaries
ENV-004 MUST check that the binary of every adapter profile in every role chain exists with a version at least `min_version`. It SHALL fail with severity error when the missing profile heads a required chain or no profile of a required chain is usable, and otherwise with severity warn.

#### Scenario: SCN-DOC-02 (−) primary agent missing vs fallback missing
- **GIVEN** the first implementer profile's binary is missing
- **WHEN** `l4 doctor --ci`
- **THEN** error, exit 3; with only a fallback binary missing: warning, exit 0

### Requirement: L4-DOC-001 (part h) ENV-005 credential names
ENV-005 MUST verify, for every profile, that the credential name it needs is present in the environment or that its stored login path exists, and it MUST report names only, never values.

#### Scenario: SCN-DOC-N12 (−) missing credential is named, value never shown
- **GIVEN** `judge-opus` with `api_key_env: ANTHROPIC_API_KEY` unset and `OPENROUTER_API_KEY` set
- **WHEN** `l4 doctor` runs
- **THEN** ENV-005 fails naming `ANTHROPIC_API_KEY` and no output contains the value of `OPENROUTER_API_KEY`

### Requirement: L4-DOC-001 (part i) ENV-006 to ENV-008 optional tool checks
Doctor MUST provide ENV-006 (warn: Laya installed and checkpoint cached, if `verifier.s1.enabled`), ENV-007 (warn: Playwright and browsers, if `gates.e2e.command` is set) and ENV-008 (warn: gitleaks if `secret_scan: gitleaks`; Serena at the pinned version if enabled). Each MUST be skipped when its feature is off.

#### Scenario: SCN-DOC-N13 (+) disabled features are skipped
- **GIVEN** `verifier.s1.enabled: false`, empty `gates.e2e.command`, `secret_scan: none` and `memory.serena.enabled: false`
- **WHEN** `l4 doctor` runs
- **THEN** ENV-006, ENV-007 and ENV-008 report status `skip`

#### Scenario: SCN-DOC-N14 (−) enabled but missing tools warn without failing the run
- **GIVEN** `secret_scan: gitleaks` and no `gitleaks` binary
- **WHEN** `l4 doctor` runs
- **THEN** ENV-008 fails with severity warn and the exit code is 0

### Requirement: L4-DOC-001 (part j) CFG-001 to CFG-004 configuration checks
Doctor MUST provide CFG-001 (error: schema valid, no literal secrets), CFG-002 (error: chains reference existing profiles, no profile has both adapter and backend), CFG-003 (error: independence satisfiable in the worst case) and CFG-004 (error: `gates.test.command` set when `tdd.mode` is not `off`).

#### Scenario: SCN-DOC-N15 (−) strict TDD without a test command
- **GIVEN** `tdd.mode: strict` and `gates.test.command: ""`
- **WHEN** `l4 doctor` runs
- **THEN** CFG-004 fails with severity error and exit 3

#### Scenario: SCN-DOC-N16 (+) consistent configuration passes all four
- **GIVEN** a configuration with valid chains, an independent third vendor and a test command
- **WHEN** `l4 doctor` runs
- **THEN** CFG-001 to CFG-004 pass
