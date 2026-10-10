## Purpose

Defines how the harness decides, deterministically and from the filesystem alone, which spec frameworks a repository uses, how units are namespaced, and the provider interface every framework adapter implements (SPEC §4.1-§4.3).

## ADDED Requirements

### Requirement: L4-DET-001 (part a) Deterministic OpenSpec detection
Detection MUST be deterministic and filesystem-only, evaluated from the repository root, with no subprocess and no network. OpenSpec (>= 1.0) is detected by `openspec/config.yaml` or `openspec/config.yml`, or by a directory `openspec/specs/` or `openspec/changes/`. `openspec/project.md` without a config file is legacy OpenSpec (< 1.0): reported as unsupported, never driven.

#### Scenario: SCN-DET-01 (+) OpenSpec detected
- **GIVEN** `openspec/config.yaml` and `openspec/changes/add-login/{proposal.md,tasks.md,specs/auth/spec.md}`
- **WHEN** `l4 plan --json`
- **THEN** frameworks = `[openspec]`, unit `openspec:add-login` with task counts equal to `openspec instructions apply --change add-login --json` `.progress`.

#### Scenario: SCN-DET-05 (−) Legacy OpenSpec is reported, not driven
- **GIVEN** `openspec/project.md` and `openspec/changes/x/` but no `config.yaml`
- **WHEN** `l4 doctor`
- **THEN** SPEC-001 error "OpenSpec < 1.0 layout; run the OpenSpec migration", exit 3; `l4 run` exits 14.

#### Scenario: SCN-DET-N11 (−) Detection never starts a process
- **GIVEN** a repository with `openspec/config.yaml` and a `PATH` that contains no `node`, `npm` or `openspec`
- **WHEN** `detect_frameworks(repo)` runs with `subprocess` and socket access patched to raise
- **THEN** it returns the OpenSpec detection without raising, proving the result depends on files only.

### Requirement: L4-DET-001 (part b) Kiro and Spec Kit signals
Kiro MUST be detected only when some `.kiro/specs/<name>/` contains `requirements.md`, `bugfix.md`, `design.md` or `tasks.md`; `.kiro/` alone is not sufficient. Spec Kit is detected by `.specify/` plus one of `memory/constitution.md`, `init-options.json` or `templates/`; a bare `specs/` folder is not sufficient. Spec Kit MUST be reported but never executed in v1.

#### Scenario: SCN-DET-02 (+) Kiro detected
- **GIVEN** `.kiro/specs/user-auth/{requirements.md,design.md,tasks.md}`
- **WHEN** `l4 plan --json`
- **THEN** frameworks = `[kiro]`, unit `kiro:user-auth`, leaves/parents/optional tasks reported per Kiro grammar.

#### Scenario: SCN-DET-03 (−) OpenSpec's Kiro integration is not a Kiro repo
- **GIVEN** an OpenSpec repo where `openspec init --tools kiro` created `.kiro/prompts/opsx-*` and `.kiro/skills/*`
- **WHEN** detection runs
- **THEN** frameworks = `[openspec]` only.

#### Scenario: SCN-DET-07 (+) Spec Kit is detected but not driven in v1
- **GIVEN** `.specify/memory/constitution.md` and `specs/001-x/tasks.md`
- **WHEN** `l4 doctor` and `l4 plan`
- **THEN** doctor warns "Spec Kit detected: not executed by v1"; `plan` lists no units; exit 0.

### Requirement: L4-DET-002 Several frameworks, namespaced units
When several frameworks are detected, all of them MUST be active and units MUST be namespaced as `<framework>:<name>`. `spec.primary` (or, when `auto`: the framework with active units, then most recent mtime, then openspec before kiro) MUST be used only for new specs created by the harness.

#### Scenario: SCN-DET-06 (+) Mixed repository
- **GIVEN** an OpenSpec change `add-a` and a Kiro spec `feat-b`, `spec.primary: auto`
- **WHEN** `l4 plan --json`
- **THEN** both `openspec:add-a` and `kiro:feat-b` are listed; each later fix unit uses its parent's framework.

#### Scenario: SCN-DET-N12 (−) Primary never re-homes an existing unit
- **GIVEN** `spec.primary: kiro` and an existing unit `openspec:add-a` that needs a fix unit
- **WHEN** the fix unit is created
- **THEN** it is `openspec:add-a-fix-1`, created by the OpenSpec provider; `primary` is consulted only for specs with no parent.

#### Scenario: SCN-DET-N13 (+) Auto primary tie-break
- **GIVEN** `spec.primary: auto`, both frameworks detected, no active units and equal mtimes
- **WHEN** the harness must create a new spec
- **THEN** `primary_framework()` returns `openspec`.

### Requirement: L4-DET-003 No framework under sdd.enforce
With `sdd.enforce: true` and no supported framework detected, `l4 run` MUST exit 14 with a message pointing to `l4 init`, before creating any branch or calling any agent.

#### Scenario: SCN-DET-04 (−) A bare `specs/` folder is not a framework
- **GIVEN** a repo with only `specs/notes.md`
- **WHEN** `l4 run`
- **THEN** exit 14, message suggests `l4 init`; no branch, no agent call.

### Requirement: L4-SPI-001 SpecProvider interface
Every framework adapter MUST implement the `SpecProvider` protocol: `framework`, `detect`, `list_units`, `load`, `validate`, `tasks`, `set_marker`, `criteria`, `create_fix_unit`, `done_gate`, `archive` and `unit_dir`, with the signatures of SPEC §4.3. A provider that lacks a member MUST be rejected at registration.

#### Scenario: SCN-DET-10 (+) Providers pass one conformance suite
- **GIVEN** the shared provider conformance tests (list, load, tasks, set_marker, criteria, validate, create_fix_unit, done_gate, archive) over equivalent OpenSpec and Kiro fixtures
- **WHEN** run for each provider
- **THEN** both pass; behaviour differences are only those documented in §4.4/§4.5.

#### Scenario: SCN-DET-N14 (−) Incomplete provider is rejected at registration
- **GIVEN** a class that implements every `SpecProvider` member except `done_gate`
- **WHEN** it is passed to `ProviderRegistry.register`
- **THEN** `ProviderContractError` names `done_gate` and the registry is unchanged.
