## Purpose

Defines the OpenSpec provider: a hermetic, harness-owned CLI invocation, root verification, strict gates before archive, OpenSpec's own task grammar, fix-unit creation and the treatment of archive-time failures (SPEC §4.4).

## ADDED Requirements

### Requirement: L4-OSP-001 (part a) Harness-owned CLI prefix
The provider MUST run the OpenSpec CLI only from a harness-owned prefix, installed with `npm install --prefix $L4_CACHE/tools/openspec-<version> @fission-ai/openspec@<version>` and executed as that prefix's `node_modules/.bin/openspec`. It MUST NOT use `npx` or any binary resolved from the worktree or `PATH`.

#### Scenario: SCN-SEC-08 (−) A planted OpenSpec package never runs
- **GIVEN** an agent added `node_modules/@fission-ai/openspec` (version 1.14.0, malicious bin) to the worktree
- **WHEN** the provider validates the unit
- **THEN** the CLI runs from `$L4_CACHE/tools/openspec-1.14.0`; the planted code does not execute (asserted by a marker file it would create).

#### Scenario: SCN-OSP-N1 (−) Missing prefix fails closed
- **GIVEN** no prefix at `$L4_CACHE/tools/openspec-1.14.0`, an `openspec` binary on `PATH`, and an install that fails
- **WHEN** the provider needs the CLI
- **THEN** `OpenSpecUnavailable` is raised with the failing install command; neither the `PATH` binary nor `npx` is executed.

### Requirement: L4-OSP-001 (part b) Hermetic machine-readable calls
Every CLI invocation MUST run with cwd set to the repository root, environment `TZ=UTC DO_NOT_TRACK=1 OPENSPEC_NO_UPDATE_CHECK=1`, and `--json` wherever the subcommand supports it.

#### Scenario: SCN-DET-09 (+) OpenSpec CLI is called machine-readably and hermetically
- **GIVEN** any OpenSpec operation
- **WHEN** the provider runs the CLI
- **THEN** every invocation uses the pinned CLI with `--json` (where supported) and the environment contains `TZ=UTC`, `DO_NOT_TRACK=1`, `OPENSPEC_NO_UPDATE_CHECK=1` (asserted on recorded command lines).

### Requirement: L4-OSP-001 (part c) Allowed subcommands
The provider MUST call only `list --json`, `show <id> --type change --json`, `validate <id> --strict --json`, `instructions apply --change <id> --json`, `archive <id> --yes` and, for fix units only (L4-OSP-005), `new change <name>`; it MUST reject any other subcommand before spawning a process.

#### Scenario: SCN-OSP-N2 (−) Subcommand outside the allowlist is rejected
- **GIVEN** a call to the CLI wrapper with `config set telemetry on`
- **WHEN** the wrapper builds the command line
- **THEN** `DisallowedSubcommand` is raised and no process is started.

### Requirement: L4-OSP-002 Verify the CLI root
Before trusting any CLI result the provider MUST verify `root.source == "nearest"` and that the reported root path equals the repository's `openspec/` directory. A `store:` redirect or an ancestor root MUST raise and schedule no unit.

#### Scenario: SCN-DET-08 (−) OpenSpec CLI resolving an ancestor root is refused
- **GIVEN** the repo is checked out inside a directory that itself contains `openspec/`, and the repo's own `openspec/` is missing `config.yaml`
- **WHEN** the provider calls the CLI
- **THEN** it detects `root.path` ≠ repo `openspec/`, raises, doctor SPEC-003 fails, no unit is scheduled.

#### Scenario: SCN-OSP-N3 (−) Declared store root is refused
- **GIVEN** `openspec/config.yaml` with `store: shared` and a CLI reply with `root.source == "declared"`
- **WHEN** the provider calls `list_units`
- **THEN** `ForeignRootError` is raised naming the source, and doctor SPEC-003 fails.

### Requirement: L4-OSP-003 Archive only through the harness gates
`archive()` MUST first run its own `done_gate()` (all non-optional tasks done) and `validate --strict`, and MUST refuse to archive otherwise, because `openspec archive --yes` archives incomplete tasks and validates non-strictly.

#### Scenario: SCN-OSP-N4 (−) Incomplete tasks block archive
- **GIVEN** a change with one `[ ]` task left and a valid strict validation
- **WHEN** `archive(unit)` is called
- **THEN** `ArchiveRefused` names the remaining task and the CLI `archive` subcommand is never invoked.

#### Scenario: SCN-OSP-N5 (−) Strict validation failure blocks archive
- **GIVEN** a change with all tasks `[x]` but `validate --strict --json` reports `valid: false`
- **WHEN** `archive(unit)` is called
- **THEN** `ArchiveRefused` carries the validation issues and the CLI `archive` subcommand is never invoked.

#### Scenario: SCN-OSP-N6 (+) Archive proceeds when both gates pass
- **GIVEN** all non-optional tasks `[x]` and a strict-valid change
- **WHEN** `archive(unit)` is called
- **THEN** the CLI runs `archive <id> --yes` once and the returned `ArchiveReport.archived_as` names the dated folder under `openspec/changes/archive/`.

### Requirement: L4-OSP-004 (part a) OpenSpec task grammar
Task parsing MUST use OpenSpec's own grammar, so the harness and `openspec instructions apply` agree: bullets `-`, `*`, `+`, `1.` and `1)`, any indentation, link bullets excluded. Only a marker of `x` or `X` MUST count as done; `[-]`, `[~]`, `[]` and `[ ]` count as not done.

#### Scenario: SCN-OSP-N7 (−) Kiro-style markers are not done in OpenSpec files
- **GIVEN** an OpenSpec `tasks.md` with one task each marked `[ ]`, `[-]`, `[~]`, `[]`, `[x]` and `[X]`
- **WHEN** `tasks(unit)` is parsed
- **THEN** exactly the `[x]` and `[X]` tasks are done and the counts equal the CLI's `progress`.

### Requirement: L4-OSP-004 (part b) Only [ ] to [x] in OpenSpec files
The harness MUST write only the transition `[ ]` to `[x]` in OpenSpec `tasks.md` files. It MUST NOT write `[-]` or `[~]`, which OpenSpec counts as not done but humans may misread as progress.

#### Scenario: SCN-OSP-N8 (−) In-progress marker is refused for OpenSpec
- **GIVEN** an OpenSpec unit and a request to set task 1.1 to the in-progress marker
- **WHEN** `set_marker(unit, "1.1", Marker.IN_PROGRESS)` is called
- **THEN** `MarkerNotAllowed` is raised and the file is unchanged.

### Requirement: L4-OSP-004 (part c) Parser disagreement is a doctor error
A disagreement between the harness parse and the CLI's `progress` for the same change MUST be reported as doctor error `SPEC-006` naming both counts, and the unit MUST NOT be scheduled.

#### Scenario: SCN-TMW-05 (−) Parser disagreement blocks scheduling
- **GIVEN** a fixture where the harness parser and `openspec instructions apply` disagree on `complete`
- **WHEN** `l4 doctor` / `l4 plan`
- **THEN** SPEC-006 error naming both counts; the unit is not scheduled.

### Requirement: L4-OSP-005 Fix units via openspec new change
Fix units MUST be created with `openspec new change <parent>-fix-<n>` and then written. When the fix carries no spec delta, the change's `.openspec.yaml` MUST contain `skip_specs: true`, because a delta-less change otherwise fails `validate --strict`.

#### Scenario: SCN-OSP-N9 (+) Delta-less fix unit validates and archives
- **GIVEN** findings and `spec_delta=None` for parent `add-login`, round 1
- **WHEN** `create_fix_unit` runs
- **THEN** `openspec/changes/add-login-fix-1/.openspec.yaml` contains `skip_specs: true` and `validate add-login-fix-1 --strict --json` reports valid.

#### Scenario: SCN-OSP-N10 (−) Existing fix change is never overwritten
- **GIVEN** `openspec/changes/add-login-fix-1/` already exists
- **WHEN** `create_fix_unit(parent, round=1, ...)` is called
- **THEN** `FixUnitExists` is raised and the existing folder is byte-identical afterwards.

### Requirement: L4-OSP-006 MODIFIED against a missing base requirement
A `MODIFIED` delta that names a requirement missing from the base spec passes `--strict` with only an INFO but fails at archive. The provider MUST treat that INFO (message starting "Archive would refuse") as a validation error.

#### Scenario: SCN-OSP-N11 (−) Archive-time INFO fails validation
- **GIVEN** a change whose `MODIFIED` delta names a requirement absent from `openspec/specs/<cap>/spec.md`, and a CLI reply `valid: true` with that INFO
- **WHEN** `validate(unit, strict=True)` runs
- **THEN** the returned `ValidationReport.valid` is false and the issue is level `error`.
