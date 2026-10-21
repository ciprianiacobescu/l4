## Purpose

Delivery-plan work before and around the push: the plan validator's baseline and review-budget checks, holding units that no plan lists, and a status that says what a holding plan does.

## ADDED Requirements

### Requirement: L4-ADO-009 The plan validator checks OpenSpec deltas against the baseline
`validate_plan.py` SHALL report, for every OpenSpec unit that a plan file plans:
- `spec_no_baseline` for a MODIFIED, RENAMED or REMOVED section of a delta whose capability has no
  `openspec/specs/<cap>/spec.md` in the working tree;
- `spec_no_purpose` for a delta of a capability new to `openspec/specs/` without a `## Purpose` of at least 50
  characters.

Each is a problem (exit 1). The script keeps to the Python standard library.

#### Scenario: SCN-ADO-26 (−) A delta with no baseline
- **GIVEN** a planned change whose delta `specs/dreaming/spec.md` has `## MODIFIED Requirements`, and no
  `openspec/specs/dreaming/spec.md`
- **WHEN** the validator runs
- **THEN** it prints `spec_no_baseline` naming the unit, the delta file and the missing baseline, and exits 1

#### Scenario: SCN-ADO-27 (+) An ADDED-only new capability with a Purpose
- **GIVEN** a planned change whose delta for a new capability has a `## Purpose` of 60 characters and only
  `## ADDED Requirements`
- **WHEN** the validator runs
- **THEN** it reports no problem for that unit

#### Scenario: SCN-ADO-28 (−) A new capability without a Purpose
- **GIVEN** the same change without its `## Purpose`
- **WHEN** the validator runs
- **THEN** it prints `spec_no_purpose` for the unit and exits 1

### Requirement: L4-ADO-010 Review budgets are checked before the push
`validate_plan.py` SHALL report `material_over_budget` for each file the readiness review would cut or leave out. It
reads a planned unit's folder at the folder budget, and a dependency at the dependency budget. A dependency is a unit
in a `depends_on`, or a prerequisite outside its batch. The script reads files the way the review reads them, with the
same limits: it reads `yolo.review.max_file_chars`, `max_folder_chars` and `max_dependency_chars` from `.l4/config.yaml`
(block style), and an absent or invalid value gives the review's default (20000, 80000, 20000; one warning on standard
error for an invalid one). A cut of a planned unit's own folder SHALL be a problem (exit 1); a dependency's cut SHALL be a warning
that leaves the exit code alone, because the review lists it as not shown in full without blocking. `l4 yolo check`
SHALL print the same lines for an admitted plan, and its exit code does not change.

#### Scenario: SCN-ADO-29 (−) A dependency over its budget
- **GIVEN** unit `b` depends on unit `a`, whose folder holds 27,148 characters with `tasks.md` read last
- **WHEN** the validator runs
- **THEN** it prints `warning: material_over_budget: openspec:a: …/tasks.md: 7148 characters cut (as a dependency of
  openspec:b)` and exits 0

#### Scenario: SCN-ADO-29a (+) A raised budget
- **GIVEN** the 27,148-character dependency of SCN-ADO-29 and `.l4/config.yaml` with `yolo.review.max_dependency_chars:
  30000`
- **WHEN** the validator runs
- **THEN** it prints no `material_over_budget` line and exits 0

#### Scenario: SCN-ADO-30 (+) Harness files do not count
- **GIVEN** a planned unit whose spec files hold 79,000 characters, and whose folder also holds a
  `verification.md` and a `.l4/` folder of 30,000 characters
- **WHEN** the validator runs
- **THEN** it reports no budget problem

#### Scenario: SCN-ADO-31 (+) The validator reads like the review
- **GIVEN** fixture folders with a cut file, an omitted file, a binary file, a ticked `tasks.md` and excluded files
- **WHEN** the validator and the review's folder reader read them
- **THEN** both list the same cut and omitted files with the same counts

#### Scenario: SCN-ADO-32 (+) l4 yolo check reports without refusing
- **GIVEN** an admissible plan with one dependency over its budget
- **WHEN** `l4 yolo check <plan>` runs
- **THEN** it prints the `material_over_budget` line and exits 0

### Requirement: L4-ADO-011 `yolo.hold` holds units that no plan lists
`yolo.hold` SHALL be a list of unit ids or `fnmatch` patterns, empty by default. A unit that matches it, and that no
plan file lists, SHALL get no agent work of any kind. `l4 status`, `l4 plan` and `l4 run --dry-run` show such a unit
as `held by yolo.hold`. A unit that a plan file lists follows that plan's rules. A merged or archived unit is never
held. The hold writes no ledger entry and calls no model. `validate_plan.py` counts a held unit as covered.

#### Scenario: SCN-ADO-33 (+) Existing specs stay put
- **GIVEN** `yolo.hold: ["openspec:a", "openspec:b"]` and no plan file
- **WHEN** `l4 run` runs
- **THEN** `a` and `b` are shown `held by yolo.hold`, no agent and no judge is called, and the run says there is
  nothing to do

#### Scenario: SCN-ADO-34 (+) A new spec still runs alone
- **GIVEN** the same hold and a new change `c`
- **WHEN** `l4 run` runs
- **THEN** `c` starts as a single unit

#### Scenario: SCN-ADO-35 (+) A pattern holds every new spec until a plan lists it
- **GIVEN** `yolo.hold: ["*"]` and a new change `c`
- **WHEN** `l4 run` runs, and later a plan file that lists `c` is reviewed and activated
- **THEN** `c` is held at first, and afterwards follows the plan

#### Scenario: SCN-ADO-36 (+) The validator counts a held spec as covered
- **GIVEN** `yolo.hold: ["openspec:a"]` and plan files that do not list `a`
- **WHEN** the validator runs
- **THEN** it does not report `uncovered: openspec:a`

### Requirement: L4-ADO-012 `l4 init --hold-existing` writes the hold
`l4 init --hold-existing` SHALL write the ids of every unit found at init into `yolo.hold`, sorted. With no unit it
writes no key and says so.

#### Scenario: SCN-ADO-37 (+) Three existing changes are held
- **GIVEN** a repository with three OpenSpec changes
- **WHEN** `l4 init --ci github --action --hold-existing` runs
- **THEN** `yolo.hold` lists the three ids in order, and a first `l4 run` says there is nothing to do

#### Scenario: SCN-ADO-38 (+) Nothing to hold
- **GIVEN** a repository with no unit
- **WHEN** `l4 init --hold-existing` runs
- **THEN** the config has no `yolo.hold`, and init says there was nothing to hold

### Requirement: L4-ADO-013 A plan that holds units says so
For a plan file that holds units and is not active, `l4 status` SHALL say how many units it holds, and that none of
them runs until the plan is fixed, completed or its file is removed.

#### Scenario: SCN-ADO-39 (+) A refused plan that holds 26 units
- **GIVEN** a refused plan that lists 26 units
- **WHEN** `l4 status` runs
- **THEN** its line reads `plan backlog: refused (holds 26 units; none of them runs until the plan is fixed, completed
  or its file is removed), 0/26 integrated, $0.00/$0.00`
