## Purpose
Defines the `l4` command surface, the process exit codes and their severity ordering, the CI rendering of exit codes, and the `outcome.json` file with its CI output mirrors.

## ADDED Requirements

### Requirement: L4-CLI-001 (part a) Command surface and global options
The `l4` console script SHALL expose every command of SPEC section 2.1 and every command MUST accept `--config PATH`, `--repo PATH`, `--log-format human|json` and `-v/-q`. A command whose implementing module does not exist yet MUST exit 2 with the message `not yet implemented` and MUST NOT raise.

#### Scenario: SCN-CLI-N8 (−) unimplemented command is a usage error
- **GIVEN** the handler module for `l4 lessons` is absent
- **WHEN** `l4 lessons list` runs
- **THEN** it prints `lessons: not yet implemented` to stderr and exits 2
- **AND** a Python traceback is never printed

#### Scenario: SCN-CLI-N9 (+) global options are accepted by every command
- **GIVEN** a repository with a valid `.l4/config.yaml`
- **WHEN** each command of section 2.1 is invoked with `--config`, `--repo`, `--log-format json` and `-v`
- **THEN** none of them fails with an unknown-option error

### Requirement: L4-CLI-001 (part b) Exit code set
Every command MUST terminate with exactly one of the codes 0 `ok`, 1 `internal_error`, 2 `usage_error`, 3 `doctor_failed`, 10 `continue`, 11 `awaiting_human`, 12 `waiting_capacity`, 13 `halted`, 14 `rejected`, defined once in an `ExitCode` enumeration. An unexpected exception MUST map to 1.

#### Scenario: SCN-CLI-N10 (−) unexpected exception becomes exit 1
- **GIVEN** a command handler that raises `RuntimeError` containing the value of `L4_FORGE_TOKEN`
- **WHEN** the command runs
- **THEN** the exit code is 1
- **AND** the traceback in the JSONL log and on the console has the token value redacted

### Requirement: L4-CLI-001 (part c) Most severe exit code wins
When several units end a run with different codes, the process exit code SHALL be the most severe by the order 1 > 2 > 3 > 13 > 14 > 11 > 12 > 10 > 0, and `outcome.json` MUST list every unit with its own outcome.

#### Scenario: SCN-CLI-03 (+) severity ordering across units
- **GIVEN** `l4 run` advances unit A to `awaiting_human` (11) and unit B to a continuation (10)
- **WHEN** the run ends
- **THEN** the process exits 11 and `outcome.json` lists both units with their own outcomes

#### Scenario: SCN-CLI-N11 (−) lower codes never mask a higher one
- **GIVEN** unit codes `[10, 12, 13, 11]` and separately `[0, 1, 14]`
- **WHEN** the most severe code is computed
- **THEN** the results are 13 and 1 respectively, and the empty list yields 0

### Requirement: L4-CLI-001 (part d) Plan exits 0 unless asked
`l4 plan` SHALL exit 0 on success whether or not units are actionable. Only with `--detailed-exitcode` MUST it exit 10 when at least one unit is actionable and 0 otherwise.

#### Scenario: SCN-CLI-01 (+) nothing to do
- **GIVEN** all units archived or merged
- **WHEN** `l4 plan --json` runs
- **THEN** exit 0; `outcome.json.units == []`; GitLab dotenv has `L4_UNITS_ACTIONABLE=0`

#### Scenario: SCN-CLI-02 (+) work pending
- **GIVEN** one unit with pending tasks
- **WHEN** `l4 plan --json` runs, and separately `l4 plan --detailed-exitcode`
- **THEN** the first exits 0 with the unit listed as `next_action: implement`; the second exits 10

#### Scenario: SCN-CLI-N12 (−) plan with an invalid config is not a success
- **GIVEN** `.l4/config.yaml` fails schema validation
- **WHEN** `l4 plan --json` runs
- **THEN** the exit code is 2, not 0

### Requirement: L4-CLI-001 (part e) CI rendering of exit codes
`l4 ci map-exit CODE` SHALL translate an exit code per the CI rendering column of SPEC section 2.2. On GitHub it MUST print an annotation and exit 0 for 10, 11 and 12, and exit 1 for every other non-zero code. On GitLab it MUST print the annotation and re-exit with the original code.

#### Scenario: SCN-CLI-N13 (+) semantic codes become warnings on GitHub
- **GIVEN** platform `github`
- **WHEN** `l4 ci map-exit 11` runs
- **THEN** stdout contains `::warning::` and the exit code is 0

#### Scenario: SCN-CLI-N14 (−) failures are never downgraded
- **GIVEN** platform `github`, and separately platform `gitlab`
- **WHEN** `l4 ci map-exit 13` and `l4 ci map-exit 11` run
- **THEN** GitHub exits 1 for 13; GitLab re-exits 13 and 11 unchanged

### Requirement: L4-CLI-002 (part a) Outcome file is always written
Every `run`, `verify`, `archive` and `plan` invocation MUST write `.l4-out/outcome.json` atomically, including when the command ends with an error, in which case `exit_code` is the code the process returns and `units` lists what is known.

#### Scenario: SCN-CLI-N15 (−) a crashing command still leaves an outcome
- **GIVEN** a handler for `l4 verify --unit X` that raises an unexpected exception
- **WHEN** the command runs
- **THEN** exit 1 and `.l4-out/outcome.json` exists with `exit_code` 1 and a valid `schema` value

### Requirement: L4-CLI-002 (part b) Outcome fields and schema
`outcome.json` MUST carry `schema` `l4/outcome@1`, `run_id`, `harness_version`, `exit_code` and per-unit `unit`, `phase_before`, `phase_after`, `tasks`, `open_questions`, `verdict`, `profiles`, `cost_usd`, `iteration`, `pr_url`, `retry_after` and `continuation`, where `continuation` is one of `not_needed`, `dispatched`, `failed`. A published JSON Schema SHALL validate it.

#### Scenario: SCN-CLI-N16 (−) invalid values are rejected by the schema
- **GIVEN** an outcome with `continuation: "maybe"` and one with `exit_code: 7`
- **WHEN** each is validated against `l4/outcome@1`
- **THEN** both are rejected naming the offending field

### Requirement: L4-CLI-002 (part c) Outcome mirrored to CI outputs
The headline fields of the outcome MUST be mirrored to `$GITHUB_OUTPUT` as `exit_code`, `units` and `phases` when that variable is set, and to the dotenv file `.l4-out/l4.env` as `L4_EXIT`, `L4_UNITS_ACTIONABLE` and `L4_PHASES`.

#### Scenario: SCN-CLI-06 (+) outcome mirrored to CI outputs
- **GIVEN** a GitHub Actions environment (`GITHUB_OUTPUT` set)
- **WHEN** `l4 run` finishes
- **THEN** `outcome.json` validates against `l4/outcome@1` and `GITHUB_OUTPUT` contains `exit_code`, `units`, `phases`

#### Scenario: SCN-CLI-N17 (−) no CI environment means no CI output file
- **GIVEN** `GITHUB_OUTPUT` is not set
- **WHEN** `l4 plan` finishes
- **THEN** no GitHub output file is created and the exit code is unaffected
