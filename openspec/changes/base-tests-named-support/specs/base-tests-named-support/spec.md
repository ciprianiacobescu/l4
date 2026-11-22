## Purpose

A support file whose change the reviewed text of a task asked the red step for stays at head when step 1 runs the
base's tests, listed. A base-tests blocker says which support files the run reverted and who changed them, its tests
reach the fix task with their failure text, and a repeated base-tests failure escalates with the way out.

## ADDED Requirements

### Requirement: L4-VER-079 A support file that the task names and its red step changed stays at head for the base's tests
When step 1 runs the base's tests (L4-VER-038), a file of the revert set SHALL stay at head for the run, and be listed
under `Pre-existing tests changed with an allowance` as `<path> kept at head for the run (task <t>: changed by its red
step, named by its reviewed text (<source>))`, when all of these hold: it is a regular file at the base and at head;
it is no ignore file; the verifier's support rule (`is_support_file`) calls it support at head; no test id of the base's
test report belongs to it (the id's class name is the file's path, its dotted module or a class of it, or a dotted class
name that ends the path without its extension); at least one harness commit changed it; and every harness commit that changed it is an `L4-TDD: red` commit of a task for which the ledger
holds a `task.unfrozen` with `reason: named_by_task`, the same unit and task, `red_sha` equal to that commit, a
`source`, and the path in its `paths` or in a `kept` entry. A person's commit needs no cover. `git diff --numstat` of
the base and head SHALL count at most 40 added and deleted lines for the file, and a binary file SHALL NOT be kept. At
most three files per task SHALL be kept this way, in path order. The others are reverted, and the row's note counts them. The rule SHALL
apply to the run of the base's tests only: the comparison of pre-existing tests (L4-VER-030, L4-VER-031) and every
other allowance keep their rules. With no base report (no baseline of the base, no earlier round's evidence, and a run at the merge base that gives none)
nothing SHALL stay by this rule. A file that fails any condition SHALL be reverted as before.

#### Scenario: SCN-VER-312 (+) A data file the task named stays at head and the base test passes
- **Given** `test/arch/modules.ts` at the base, task 1.1's red commit that adds an edge to it, a `task.unfrozen{reason:
  named_by_task, red_sha: <that commit>, source: plan:p@d, kept: [{path: test/arch/modules.ts, why: a red test of this
  task}]}`, and the unchanged base test `test/arch/repo.test.ts`, which passes only with the head version
- **When** step 1 runs the base's tests
- **Then** `verify.base_tests.reverted` does not hold the file, the allowances list `test/arch/modules.ts kept at head
  for the run (task 1.1: changed by its red step, named by its reviewed text (plan:p@d))`, and no base-tests blocker is
  raised

#### Scenario: SCN-VER-313 (−) A file another task's commit also changed is reverted
- **Given** the file of SCN-VER-312, also changed by task 1.2's red commit, whose text does not name it
- **When** step 1 runs the base's tests
- **Then** the file is reverted and the base test's failure is a blocker, as before

#### Scenario: SCN-VER-314 (−) An ignore file, an added file, a test module, an older red and a fourth file are reverted
- **Given** a red commit of a named task that changed `.gitignore`, added `test/arch/new.ts`, changed
  `test/arch/repo.test.ts` and four named data files, and rewrote a fifth named data file in 60 lines; and a
  `task.unfrozen{named_by_task}` whose `red_sha` is an earlier red commit of a reopened task
- **When** step 1 runs the base's tests
- **Then** only the first three data files in path order stay at head, the note counts one more, and every other
  file is reverted or set aside as before

#### Scenario: SCN-VER-315 (−) The comparison of pre-existing tests is unchanged
- **Given** a Python file that matches a test glob and a support glob, that the task names and red changed, and in
  which red changed a test that exists at the base
- **When** step 1 runs
- **Then** `a pre-existing test was changed` is still a blocker (L4-VER-030)

#### Scenario: SCN-VER-316 (+) A unit in flight from 0.4.59 keeps its named file on its next round
- **Given** a ledger written by 0.4.59 that holds the `task.unfrozen{named_by_task}` of SCN-VER-312, and a round 1
  that failed on the base test
- **When** round 2 runs on 0.4.60
- **Then** the file stays at head and is listed, and the ledger folds as before

### Requirement: L4-VER-080 A base-tests blocker names the reverted support files and carries its tests' failure text
When step 1's run reverted a support file, the detail of `a pre-existing test fails on the unit's code` and of `a
pre-existing test no longer runs on the unit's code` SHALL start with `with the unit's test and support files at their
base version (support files reverted: <path> (task <t>), ...; <k> files in all), these base tests fail:` (`no longer
run:` for the second), at most 5 support files, each with the tasks of the harness commits that changed it, `(a
person)` when a person's commit changed it and no task's did, or `(a harness commit)` when only a harness commit with no
task changed it. The detail SHALL NOT say that a test passes at head. `verify.base_tests` SHALL carry `support_reverted:
[{path, tasks, people}]`, at most 20 entries. Each failing base test of the blocker SHALL have a record in the round's
`failures` with `gate: base-tests`, its kind, its first line and the excerpt of L4-VER-078 (bounded and redacted the
same way). The failure block of a fix task for `a pre-existing test fails on the unit's code` SHALL hold every
`base-tests` record (L4-IMP-102). Readers of `failures` that filter by gate SHALL ignore these records. With no
reverted support file, the detail SHALL be as before.

#### Scenario: SCN-VER-317 (+) The blocker names the file and the task that changed it
- **Given** the unit of SCN-VER-313
- **When** step 1 raises the blocker
- **Then** its detail starts with `with the unit's test and support files at their base version (support files
  reverted: test/arch/modules.ts (task 1.1, 1.2); 5 files in all), these base tests fail:` and then names
  `test/arch/repo.test.ts` with its first line

#### Scenario: SCN-VER-318 (+) The fix chore sees the failure text of the base test
- **Given** the round of SCN-VER-317, whose failing case has a body with `AssertionError: expected [ 'src/a -> src/b'
  ] to deeply equal []`
- **When** the fix unit is written and its fix chore is prompted
- **Then** `verdict.json` holds the record of `test/arch/repo.test.ts` with `gate: base-tests` and an `excerpt` with
  that line, and the fix unit's `proposal.md` and the chore's prompt hold it in the failure block

#### Scenario: SCN-VER-319 (−) A secret is not recorded, and other readers ignore the records
- **Given** a failing base test whose body holds a token-shaped value
- **When** step 1 writes the records and the fix unit is planned
- **Then** no part of the token is in `verdict.json`, and no repair chore and no e2e duty is made from a
  `base-tests` record

### Requirement: L4-VER-081 A repeated base-tests failure escalates with the reverted support files and the way out
When a round escalates `same_failure` and its blocking findings hold `a pre-existing test fails on the unit's code` or
`a pre-existing test no longer runs on the unit's code`, and the newest `verify.base_tests` of the unit up to that
round names a reverted support file that a task changed, the escalation's text SHALL start with `base versions of
support files fail a pre-existing test; tag the task that changed one [test-infra] if its change is intended, or fix
the code, then l4 retry: <path> (task <t>), ...`, at most 3 files and 300 characters, followed by `; ` and the
`same_failure` detail. The way out comes before the files, so a cut of the reason at 300 characters drops files, not
the way out. The code SHALL stay `same_failure`. With no such entry
(a 0.4.59 event), the text SHALL be the detail alone.

#### Scenario: SCN-VER-320 (+) The escalation tells the person which task to tag
- **Given** the unit of SCN-VER-317, whose fix chore committed only its tick, and a round 2 that fails the same way
- **When** the fix loop escalates
- **Then** the reason starts with `base versions of support files fail a pre-existing test; tag the task that changed
  one [test-infra] if its change is intended, or fix the code, then l4 retry: test/arch/modules.ts (task 1.1, 1.2)` and
  holds `round 2 failed the same way as round 1`

#### Scenario: SCN-VER-321 (−) Another repeated failure keeps its text
- **Given** a round that fails `test gate failed` the same way twice, and a round whose `verify.base_tests` has no
  `support_reverted`
- **When** each escalates `same_failure`
- **Then** each reason is `round <n> failed the same way as round <m>: ...` as before

#### Scenario: SCN-VER-324 (−) A file that a base test belongs to is reverted, whatever its name
- **Given** `src/__tests__/render.ts`, `test/arch/repo.ts` and `test/helpers/x.ts`, which have no test-looking name,
  that task 1.1's reviewed text names and its red commit changed (each in 40 lines or fewer), and a base report that
  holds a test id whose class name is that path
- **When** step 1 runs the base's tests
- **Then** each file is reverted, `verify.base_tests.reverted` holds it, and no allowance lists it

#### Scenario: SCN-VER-325 (−) With no base report nothing stays by this rule
- **Given** a file of SCN-VER-312, and a unit with no baseline of its base, no earlier round's evidence and a run at the
  merge base that gives no report
- **When** step 1 runs the base's tests
- **Then** the file is reverted and no allowance lists it, and a unit that names no such file never runs the merge base
  for this

#### Scenario: SCN-VER-326 (+) A data file with no test of its own stays, and a plan named people is no person's
- **Given** `src/__tests__/data.ts`, named by task 1.1 and changed by its red commit, a base report whose ids belong to
  other files, and a `source` of `plan:people@d`
- **When** step 1 runs the base's tests
- **Then** the file stays at head, and the line is in `allowed_tests` and not in `human_tests`

#### Scenario: SCN-VER-327 (+) A file that a harness commit with no task changed is not called a person's
- **Given** a reverted support file that only a harness commit with no `L4-Task` trailer (a lessons commit) changed, and
  another that a person's commit also changed
- **When** step 1 raises the blocker
- **Then** the lead names the first as `(a harness commit)` and `support_reverted` holds `people: false` for it; the
  second is `(a person)`

#### Scenario: SCN-VER-328 (−) A name that is not the path, a link, a deleted file and another reason are reverted
- **Given** a data file `x.ts` that red changed and whose task names `x.tsx` (and the reverse, and `x` and `sub/x.ts`);
  a named file that is a link at head, a link at the base, or deleted at head; and a `task.unfrozen` of reason
  `human_answer`, `delegate_answer` or none that holds a source, the red commit and a `kept` entry for the file
- **When** step 1 runs the base's tests
- **Then** every such file is reverted: the rule reads the exact path, a regular file at both revisions and the reason
  `named_by_task`
