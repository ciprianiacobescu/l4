## Purpose
Non-functional guarantees of the harness (speed, overhead, determinism, dependencies, platforms, evidence for external facts) and the live scenario that proves the harness end to end on the reference GitLab project and a GitHub repository.

## ADDED Requirements

### Requirement: L4-NFR-001 Planning speed
`l4 doctor --ci` and `l4 plan` MUST each complete in less than 30 seconds on a repository with 200 units, excluding `--live` and `--sweep`.

#### Scenario: SCN-NFR-01 (+) Plan is fast on large repositories
- **GIVEN** a fixture with 200 OpenSpec changes
- **WHEN** `l4 doctor --ci` and `l4 plan --json` run on a CI-sized machine
- **THEN** each completes in under 30 s

#### Scenario: SCN-NFR-06 (−) A slow plan fails the benchmark
- **GIVEN** the 200-change fixture and a planner patched to sleep so that `l4 plan` takes 31 s
- **WHEN** the benchmark test runs
- **THEN** the benchmark fails and its message names the measured seconds and the 30 s limit

### Requirement: L4-NFR-002 Harness overhead per step
The harness overhead per task step, excluding agent and gate time, MUST be below 5 seconds.

#### Scenario: SCN-NFR-02 (+) Harness overhead is bounded
- **GIVEN** a simulation with zero-latency fake adapters and gates
- **WHEN** 20 task steps run
- **THEN** the mean harness time per step is under 5 s

#### Scenario: SCN-NFR-07 (−) Overhead excludes agent and gate time but not harness waits
- **GIVEN** a simulation in which each fake agent step sleeps 2 s and a harness-side operation is patched to sleep 6 s
- **WHEN** 20 task steps run
- **THEN** the measured harness time per step is at least 6 s, excludes the agent sleep, and the benchmark fails

### Requirement: L4-NFR-003 Determinism
Given the same repository state, configuration and fake adapters, `l4 plan` output and simulation event sequences MUST be byte-identical across runs, timestamps excluded.

#### Scenario: SCN-NFR-08 (+) Two runs are byte-identical
- **GIVEN** the same fixture repository, config and fake adapters
- **WHEN** `l4 plan --json` and `l4 simulate happy-openspec --json` run twice
- **THEN** after removing `ts`, `run_id` and `duration` fields the outputs are byte-identical

#### Scenario: SCN-NFR-09 (−) Unordered output is detected
- **GIVEN** a planner patched to iterate units in set order with hash randomisation enabled
- **WHEN** the determinism test runs twice with different `PYTHONHASHSEED` values
- **THEN** the comparison fails and prints the first differing line

### Requirement: L4-NFR-004 Approved runtime dependencies only
The runtime dependencies of the built wheel MUST be a subset of `pydantic`, `pyyaml`, `httpx`, `jsonschema` and `typer` or `click`, with the optional extras `[laya]` and `[serena]` excluded, and `litellm` MUST NOT appear.

#### Scenario: SCN-NFR-03 (−) No unapproved runtime dependencies
- **GIVEN** the built wheel
- **WHEN** its declared runtime dependencies are listed
- **THEN** they are a subset of the approved list (extras excluded); `litellm` is absent

### Requirement: L4-NFR-005 Platforms
CI and live runners MUST be Linux (bubblewrap, container or sandbox-user isolation); macOS MUST be supported for local development only with `sandbox.mode: user` or `container`, and doctor MUST report the reduced isolation; Windows is best effort.

#### Scenario: SCN-NFR-04 (+) Linux CI; macOS unit tests
- **GIVEN** the harness CI matrix
- **WHEN** the full test and simulation suites run on Linux and the unit tests on macOS
- **THEN** all pass

#### Scenario: SCN-NFR-05 (+) macOS for local development
- **GIVEN** a developer's macOS machine with `ci.platform: local`
- **WHEN** `l4 doctor` and `l4 run --dry-run` run with `sandbox.mode: user`
- **THEN** both work; SANDBOX-001 is reported as a warning (reduced isolation: no bubblewrap, no `/proc` checks), not an error

#### Scenario: SCN-NFR-10 (−) macOS is not accepted for a CI platform
- **GIVEN** a macOS machine with `ci.platform: gitlab`
- **WHEN** `l4 doctor --ci` runs
- **THEN** SANDBOX-001 is an error (it is a warning only for `ci.platform: local`) and the exit code is 3

### Requirement: L4-NFR-006 External facts have evidence before GA
Every `[U]` fact in SPEC section 8.3 MUST have a contract test or a `LIVE-*` doctor check before the corresponding adapter is labelled GA, and an adapter that lacks one MUST be reported as not GA.

#### Scenario: SCN-NFR-11 (−) An unverified adapter fact blocks the GA label
- **GIVEN** an adapter registered with one `[U]` fact and no contract test or `LIVE-*` check
- **WHEN** the GA audit (`scripts/check_ga.py`) runs
- **THEN** the adapter is listed as not GA with the fact named, and the script exits non-zero

#### Scenario: SCN-NFR-15 (+) A fact with a recorded contract test is GA-eligible
- **GIVEN** an adapter whose every `[U]` fact maps to an existing contract test in `tests/contract/`
- **WHEN** the GA audit runs
- **THEN** the adapter is listed as GA-eligible and the script exits 0

### Requirement: §20.4 (part a) Live walking skeleton on the reference GitLab
The live scenario MUST run on `example-group/dummy-agentic` (GitLab 17.5.2 CE, project id 118) through runner #12 `l4-runner`, with only the documented install commands run by a human, and MUST show in order: `l4 doctor` passing in a pipeline job; a seeded OpenSpec change implemented by a real agent CLI with a red commit before a green commit; a verification with deterministic gates and one independent judge writing `verification.md`; an opened MR merged by a human followed by a post-merge archive MR; and an ambiguous change producing `questions.md` that resumes after a committed human answer.

#### Scenario: SCN-NFR-12 (+) The M1 live scenario passes end to end on GitLab
- **GIVEN** `example-group/dummy-agentic` initialised with `l4 init --ci gitlab`, the masked variable `L4_FORGE_TOKEN` set, and a seeded change `add-greeting`
- **WHEN** a push pipeline runs and a human merges the resulting MR
- **THEN** the pipeline jobs ran on runner id 12; the branch history has a red commit before a green commit; `verification.md` records PASS with one judge; the MR carried label `l4:in_review` and status `l4/openspec/add-greeting` success; after the merge a MR on branch `l4/archive/openspec/add-greeting` appears; the ambiguous change `add-ambiguous` yields `questions.md`, and a committed answer resumes it

#### Scenario: SCN-NFR-13 (−) The live run fails closed without a valid token
- **GIVEN** the same project with the masked variable `L4_FORGE_TOKEN` replaced by an invalid value
- **WHEN** a push pipeline runs
- **THEN** `doctor --ci` fails in the detect job with exit 3 before any agent call, no child pipeline is created, no branch or MR is created and the ledger gains no agent event

### Requirement: §20.4 (part b) Full live scenario
The full live scenario MUST additionally exercise: probe and fallback with the Codex window excluded by configuration, red/green, a forced clarification, and a forced verifier failure that produces a fix unit, a PASS, the archive and a ready MR.

#### Scenario: SCN-NFR-14 (+) Fallback, clarification and fix loop are observed live
- **GIVEN** the reference project with `min_remaining_percent: 101` on the Codex profile and a seeded change whose first implementation fails verification
- **WHEN** the pipeline runs to completion
- **THEN** the ledger shows `availability.fallback` away from Codex, `question.raised` then `question.answered`, `verify.verdict` FAIL then `fix.spawned` then `verify.verdict` PASS, and the MR is ready with label `l4:in_review`

### Requirement: §20.4 (part c) GitHub parity run
The live scenario MUST be repeated on a GitHub test repository with the GitHub Actions template, and the v1 release MUST NOT be tagged before both runs pass.

#### Scenario: SCN-NFR-16 (−) No release tag with a failed or missing GitHub run
- **GIVEN** a passing GitLab live record and no GitHub live record
- **WHEN** the release check (`scripts/check_release.py`) runs
- **THEN** it exits non-zero naming the missing GitHub live run
