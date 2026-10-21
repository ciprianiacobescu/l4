## Purpose

A delivery plan can be checked before it is pushed, with the installed `l4`.

## ADDED Requirements

### Requirement: L4-YOLO-034 A plan is checked in the working tree before the push
`l4 yolo check PLAN --worktree` SHALL read the plan files and the units from the working tree and run the admission of
`l4 yolo check` on them, and SHALL also report, across all plan files of the working tree, `uncovered` (a unit no plan
lists as planned or excluded, except a derived unit whose parent is listed) and `covered_twice` (a unit two plan files
list). It SHALL print every finding, then the order of the units and the budget warnings, write nothing, and exit 0
when the plan is admitted and nothing is uncovered or covered twice, else 2. A plan file that is not in the working tree
SHALL be exit 2 naming the path. For the same tree, its coverage findings SHALL be the ones `validate_plan.py` prints.
`l4 yolo draft` and the worktree review SHALL name this command in their hints.

#### Scenario: SCN-YOLO-86 (+) A plan on a feature branch is checked before the push
- **GIVEN** a working tree with three new Kiro specs, a plan file `.l4/plans/multitenancy.json` that lists them with their
  dependencies and excludes the two held changes, none of it pushed
- **WHEN** `l4 yolo check multitenancy --worktree` runs
- **THEN** it prints `multitenancy: admitted (working tree)` and the order, writes nothing, and exits 0

#### Scenario: SCN-YOLO-87 (−) A spec no plan lists is uncovered
- **GIVEN** the working tree of SCN-YOLO-86 with one held change left out of `exclude`
- **WHEN** the check runs
- **THEN** it prints `uncovered: openspec:add-llm-vision-provider` and exits 2, as `validate_plan.py` does for that tree

#### Scenario: SCN-YOLO-88 (−) A dependency cycle and an unknown unit are refused before the push
- **GIVEN** a plan file whose units depend on each other in a cycle and name a unit that does not exist
- **WHEN** the check runs
- **THEN** it prints the `cycle` and `unknown_unit` findings, writes nothing, and exits 2

#### Scenario: SCN-YOLO-89 (+) The draft names the command
- **GIVEN** a working tree with specs that no plan lists
- **WHEN** `l4 yolo draft p` runs
- **THEN** its "Next:" lines name `l4 yolo check p --worktree`
