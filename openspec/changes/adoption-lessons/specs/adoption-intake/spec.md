## Purpose

What a unit must pass before an agent runs: the evidence plugins cannot be shadowed by a repository file, and an OpenSpec unit is strictly validated with its findings shown in full and a way out.

## ADDED Requirements

### Requirement: L4-ADO-001 The test gate refuses a module that shadows an evidence plugin
Before it runs a gate command whose environment loads `l4_trace` or `l4_cov` (a `-p` option in `PYTEST_ADDOPTS`), the
harness SHALL look in the command's working directory for an importable module of that name: a module file with an
importable suffix, or a package `__init__`. If it finds one, the command MUST NOT start, and the gate fails with a
reason that names the file. The gate environment SHALL NOT gain `PYTHONSAFEPATH`.

#### Scenario: SCN-ADO-01 (−) A root l4_trace.py stops the gate
- **GIVEN** a worktree whose root holds `l4_trace.py`
- **WHEN** a gate runs with the trace plugin in its environment
- **THEN** no process is started, and the gate fails with a reason that names `l4_trace.py` and the evidence plugin it
  would replace

#### Scenario: SCN-ADO-02 (+) A nested module or a root coverage.py is no shadow
- **GIVEN** a worktree holding `src/pkg/l4_trace.py` and a root `coverage.py`, and no root `l4_trace` or `l4_cov`
- **WHEN** the test gate runs
- **THEN** the command runs as before

#### Scenario: SCN-ADO-03 (+) Gates keep their import path
- **GIVEN** a gate command `python scripts/check.py`, where the script imports a sibling module of `scripts/`
- **WHEN** the gate environment is built and the command runs
- **THEN** the environment has no `PYTHONSAFEPATH`, and the import succeeds

### Requirement: L4-ADO-007 A single OpenSpec unit is validated strictly before any agent runs
An OpenSpec unit SHALL be validated strictly in the phases where the intake lint runs, before any agent or probe, as a
Kiro unit is. The checks are the provider's strict validation and the Purpose rule of L4-OSP-007: a delta for a
capability new to `openspec/specs/` needs a `## Purpose` of at least 50 characters.

Any error SHALL reject the unit with exit 14 and a `unit.rejected` entry that carries every reason.

#### Scenario: SCN-ADO-20 (−) A MODIFIED delta on a missing capability
- **GIVEN** a change whose delta modifies `dreaming`, with no `openspec/specs/dreaming/spec.md` on the base, and no
  plan
- **WHEN** `l4 run` reaches the unit
- **THEN** the unit is rejected with exit 14 before any agent starts, and the reason holds the archive refusal and the
  hint of L4-ADO-008

#### Scenario: SCN-ADO-21 (−) A new capability without a Purpose
- **GIVEN** a change whose delta adds requirements to a capability that `openspec/specs/` lacks, and that has no
  `## Purpose`
- **WHEN** `l4 run` reaches the unit
- **THEN** the unit is rejected with exit 14, and the reason names the missing Purpose

#### Scenario: SCN-ADO-22 (+) A valid change starts as before
- **GIVEN** a change that validates strictly
- **WHEN** `l4 run` reaches the unit
- **THEN** its first task starts, and no `unit.rejected` entry is written

### Requirement: L4-ADO-008 Intake findings are shown in full, with a way out
An intake failure SHALL carry every error, each cut at no fewer than 600 characters. The plan step's refusal line SHALL
list one finding per line: at most 10, then how many are left and `l4 yolo check <plan>`.

An archive refusal for a missing capability SHALL be followed by the harness's hint. The hint says:
- archive the change that creates the capability first, or write the delta as `## ADDED Requirements`;
- a unit cannot modify what another unit of the same plan only adds.

#### Scenario: SCN-ADO-23 (−) Every finding is printed
- **GIVEN** a plan with 8 units that each fail intake
- **WHEN** the plan step refuses it
- **THEN** the log has one line per finding, 8 in all

#### Scenario: SCN-ADO-24 (−) Two errors in one unit
- **GIVEN** a change with a MODIFIED delta that drops a scenario and another that targets a missing capability
- **WHEN** intake runs
- **THEN** the detail holds both messages in full, OpenSpec's sentence "Copy the omitted scenarios into the MODIFIED
  block" included, and the hint for the missing capability

#### Scenario: SCN-ADO-25 (−) Twelve findings
- **GIVEN** a plan refused with 12 findings
- **WHEN** the plan step prints the refusal
- **THEN** it prints 10 finding lines and then `… and 2 more: l4 yolo check <plan>`
