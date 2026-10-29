## Purpose

A unit whose task tells the implementer to create a file that no agent step may write is stopped before any run, with
the fix named; and the advice an agent and a person get after such a removal names the forbidden path, not a frozen test.

## ADDED Requirements

### Requirement: L4-YOLO-092 A task that names a forbidden file is refused at intake
The intake of a unit (plan check, review, activation and `go`; and the start of a unit before it implements) SHALL
refuse a unit with the blocker `forbidden_path` when a pending required task's own text names a file that does not
exist in the tree checked and that a glob of `odd.forbidden_paths` matches, unless the task's line says not to touch it.
The message SHALL name the task, the path, the glob and the fixes: an explicit `odd.forbidden_paths` list on the base
branch without that glob (not offered for a contract glob), or a person's commit of the file on the base branch first.
The same match for a file that exists, a directory, or a mention outside the tasks SHALL be a warning, and SHALL NOT
refuse the unit.

## MODIFIED Requirements

### Requirement: L4-IMP-006 (amendment, the guard's note to the agent)
A removal under a glob of `odd.forbidden_paths` SHALL tell the agent that no agent step may write the path and no
answer lifts that, and that a task that needs it is reported blocked with a technical question naming the path and
the rule.

### Requirement: L4-IMP-015 (amendment, the harness note on a question)
A technical question raised after a forbidden-path removal in the same attempt, or naming such a path, SHALL carry a
note that names the path and the glob, says that no answer lets an agent write it, and names the two fixes (a person's
commit on the unit branch, or a narrowed `odd.forbidden_paths` on the base branch); it SHALL NOT carry the unfreeze
note.

#### Scenario: SCN-YOLO-246 (−) a task that creates a forbidden migration is refused
- **WHEN** a unit's pending task 1.2 says "Create `app/migrations/0001_initial.py`", the file does not exist, and
  `odd.forbidden_paths` is the default
- **THEN** `l4 yolo check` reports the `intake` finding `forbidden_path` naming task 1.2, the path, `**/migrations/**`
  and both fixes, and the plan is not admitted

#### Scenario: SCN-YOLO-247 (+) a narrowed list admits it
- **WHEN** `odd.forbidden_paths` is set to a list without `**/migrations/**`
- **THEN** the unit is admitted

#### Scenario: SCN-YOLO-248 (+) an existing file, a ticked task or a "do not" line is not a blocker
- **WHEN** the named file exists, or the task is `[x]`, or the line reads "do not touch `app/migrations/0001_initial.py`"
- **THEN** there is no blocker; the existing file gives a warning that `l4 yolo check` prints, exit 0

#### Scenario: SCN-YOLO-249 (+) a directory or a design mention is a warning
- **WHEN** a task names `infra/` or design.md names `infra/compose.yml`
- **THEN** a warning names the path and the glob, and the unit is admitted

#### Scenario: SCN-YOLO-250 (+) a contract glob offers only the person's commit
- **WHEN** a pending task names `.github/workflows/new.yml`
- **THEN** the blocker's fix names a person's commit and does not offer `odd.forbidden_paths`

#### Scenario: SCN-YOLO-251 (−) a single unit is rejected before any agent runs
- **WHEN** `l4 run --unit` starts such a unit in phase `ready` (OpenSpec or Kiro)
- **THEN** `unit.rejected` names `forbidden_path`, the exit is 14, and no agent step ran; a unit already implementing is
  not rejected

#### Scenario: SCN-IMP-423 (+) the retry hint names the forbidden path
- **WHEN** a green step writes `app/migrations/0001_initial.py` and the guard removes it under `**/migrations/**`
- **THEN** the next attempt's prompt says no agent step may write it and to report blocked with a technical question

#### Scenario: SCN-IMP-424 (+) the question note names the right fix
- **WHEN** after that removal the step raises a technical question
- **THEN** its harness note names the path and the glob and the two fixes, and does not mention unfreezing a test
