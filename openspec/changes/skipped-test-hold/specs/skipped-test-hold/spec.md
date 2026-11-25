## Purpose

An old test that step 3 finds skipped, in a test file the unit changed, is a finding only when the unit added or changed
a skip that can affect it. When the skip predates the unit it is a hold that a person answers, and no fix unit is
made for it, because a fix unit cannot change test files. A unit that already has a fix unit for the old finding can be
moved on with `l4 retry`.

## ADDED Requirements

### Requirement: L4-VER-092 A skip that predates the unit is a hold, not a finding
Step 3 SHALL decide, for each old test that the gate report holds as `skipped` in a test file the unit changed, whether
its skip predates the unit. The skip SHALL predate the unit only when all of these hold: the file is reported modified
by `base..head` (not added, not renamed, not deleted); the file's base and head blobs are read and parse as Python; the
test maps to a qualified name of the file that is a test at the base; no skip construct was added or changed between the
base and the head in a scope that can skip that test (the test, its class, `<module>`, or a non-test function or method
of the file), by `scan.skip_constructs` as a multiset difference of the head's constructs over the base's, so that a
removed skip never counts and a changed condition, a new alias use or a new `importorskip` does; and, when the file
holds no skip construct in those scopes, the unit changed no file that matches `tdd.test_support_globs` or
`tdd.runner_config_files`. A test whose skip predates the unit SHALL NOT be named in the finding `existing tests are
skipped in a changed test file`; the tests of one file SHALL be one hold of kind `skipped` with the text `skipped:
existing tests in `<path>` are skipped, and this unit did not add or change a skip that can affect them (<n> tests)`.
Any other old skipped test of a changed file, and every case in which a blob cannot be read or parsed, SHALL stay in the
deterministic major finding as before. The hold SHALL join the round at step 3, whether diff coverage is on or off, and
SHALL be listed in `evidence.holds` of `verdict.json` with kind `skipped` and in `tests_ran.summary.skipped_predating`.
The check SHALL NOT run a test and SHALL NOT read a base report.

#### Scenario: SCN-VER-372 (+) A stack-gated test whose assertion the unit edited is a hold
- **Given** `tests/test_live.py` at the base has `@pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason=...)` on `test_a` and `test_b`, the unit changed one assertion line in each, and the gate report holds both as `skipped`
- **When** step 3 collects evidence
- **Then** the round has no finding `existing tests are skipped in a changed test file`
- **And** it has one hold `skipped: existing tests in `tests/test_live.py` are skipped, and this unit did not add or change a skip that can affect them (2 tests)`, the verdict is NEEDS_HUMAN, and `tests_ran.summary.skipped_predating` lists both ids

#### Scenario: SCN-VER-373 (−) A skip the unit added stays a deterministic finding
- **Given** the unit added `@pytest.mark.skip` above `test_a`, which exists at the base, and `test_a` is skipped
- **When** step 3 collects evidence
- **Then** the major finding names `test_a`, there is no hold for it, and no person can waive the finding

#### Scenario: SCN-VER-374 (−) A changed condition on a continuation line is a changed skip
- **Given** `test_a` carries a two-line `@pytest.mark.skipif(` whose second line the unit changed from `os.getenv("A") != "true"` to `os.getenv("B") != "true"`
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and in no hold

#### Scenario: SCN-VER-375 (+) A skip the unit added to one test does not touch another test of the file
- **Given** the unit added `@pytest.mark.skip` to `test_a`, `test_b` was skipped by an unchanged `skipif` and is skipped now
- **When** step 3 collects evidence
- **Then** `test_a` is in the finding and `test_b` is in the hold of the file

#### Scenario: SCN-VER-376 (−) A skip construct in a shared scope touches every test of the file
- **Given** one of: the unit applied an existing alias `@requires_stack` to `test_a`; added `pytestmark = pytest.mark.skipif(...)`; added `docker = pytest.importorskip("docker")` at module level; gave a fixture of the file a `pytest.skip(...)` call
- **When** step 3 collects evidence
- **Then** every old skipped test of the file is in the finding and none is in a hold

#### Scenario: SCN-VER-377 (−) A file or test that cannot be compared stays a finding
- **Given** each of: the test file is new in the unit; the file was renamed; the skipped test did not exist at the base (renamed or moved to another class); the head blob does not parse; the base blob is over `MAX_SOURCE_BYTES`; `git show` fails
- **When** step 3 collects evidence
- **Then** the old skipped tests of that file are in the finding and in no hold, and no exception escapes the evidence step

#### Scenario: SCN-VER-378 (+/−) A skip with no construct in the file depends on support files
- **Given** `test_a` is skipped, its file holds no skip construct in any scope that can skip it, and the unit changed only that file
- **When** step 3 collects evidence
- **Then** `test_a` is in the hold
- **And** when the unit also changed `tests/conftest.py` (or a file of `tdd.runner_config_files`), `test_a` is in the finding instead

#### Scenario: SCN-VER-379 (+) The hold is raised when diff coverage is off
- **Given** `verifier.evidence.diff_coverage.mode: off` and the case of SCN-VER-372
- **When** the ladder runs
- **Then** the hold is in `result.holds` and is asked, and it is in `later_holds` of no step

#### Scenario: SCN-VER-380 (+) Nothing changes when no skip predates the unit
- **Given** `check_tests_ran` is called without `predating`, or with an empty set
- **When** an old skipped test lies in a changed file
- **Then** the finding and `TestsSummary` are as before, and a `verdict.json` that has no `skipped_predating` reads as an empty tuple

### Requirement: L4-VER-093 The skipped-test hold is asked as a verdict question, bound to the file, and its reject makes no fix unit
The hold of L4-VER-092 SHALL be asked like any hold (`Kind: verdict`, target `H-` and eight hex digits of its text). Its
kind SHALL be read from the text prefix `skipped: existing tests in ` (`hold_kind` returns `skipped`); `hold_subjects`
SHALL return none for it, so no judge finding is settled by its answer. The question SHALL name the file and the count,
list the skipped test ids, say that the unit's diff adds or changes no skip that can affect them and that no base run was
made, say that an `accept` means the person ran them where they can run or knows they pass there and holds for this
content of the file only, and say that `reject: <reason>` ends the round because a fix unit cannot change test files. A
person's `accept` SHALL be bound (`result.hold_views`) to the head blob of the file and the full sorted list of its
skipped ids, so that an edit of the file or a change of the skipped set voids it and the hold is asked again. An `accept`
SHALL waive the hold. A `reject`, with or without a reason, with or without a `WHEN ... THEN ...`, SHALL become a finding
of source `human`, severity major, titled `Rejected hold: a skipped test is not accepted`, which the fix planner SHALL
list as not converted; no fix unit SHALL be written for it; the round SHALL end escalated with the reason
`skipped_tests_rejected`, and `l4 status` SHALL say the way out: a commit of the person's own on the unit branch that
removes the skip or makes the tests able to run in the gate, then `l4 retry --unit <unit> --reason TEXT`, or an accept
that replaces the answer once the tests ran.

#### Scenario: SCN-VER-381 (+) The question names what a person needs to decide
- **Given** the hold of SCN-VER-372
- **When** the verdict question is raised
- **Then** its context lists `tests.test_live::test_a` and `tests.test_live::test_b`, says no base run was made, offers `accept` and `reject: <reason>`, and does not ask for a `WHEN ... THEN ...`

#### Scenario: SCN-VER-382 (+) An accept waives the hold and the round can pass
- **Given** the hold of SCN-VER-372 and `accept ran against the stack on 2026-11-25`
- **When** the next round ends with no other finding
- **Then** the hold is resolved, the verdict is PASS, and the question is not asked again

#### Scenario: SCN-VER-383 (−) An edit of the file voids the accept
- **Given** the accept of SCN-VER-382 and a later commit that changes `tests/test_live.py`
- **When** the next round runs
- **Then** the hold has a new binding, the accept is not in force, and the hold is asked again

#### Scenario: SCN-VER-384 (−) A reject is the person's finding and makes no fix unit
- **Given** the hold of SCN-VER-372 and `reject: run them in the gate. WHEN the gate runs THEN they pass`
- **When** the round settles its holds
- **Then** there is one finding titled `Rejected hold: a skipped test is not accepted`, source `human`, with the person's text
- **And** the fix planner lists it as not converted (the scenario does not make a task), no fix unit is written, and the unit is escalated with `skipped_tests_rejected` and the way out of this requirement

#### Scenario: SCN-VER-385 (+) An accept does not settle a judge finding about the file
- **Given** the hold of SCN-VER-372 and a blocking judge-only finding whose text names `tests/test_live.py`
- **When** the hold is accepted
- **Then** the finding is not settled by it and is asked on its own

### Requirement: L4-VER-094 Only a person answers a skipped-test hold
The delegate SHALL NOT answer a skipped-test hold: `_without_a_call` SHALL return a reason for kind `skipped`, so the
question is escalated to a person with no model call, and `check_reply` SHALL refuse both an accept and a reject of it
with status `escalated`. The delegate prompt SHALL say so. A verdict of such a hold whose `by` is not `human` (`agent`,
`delegate`, `clarifier`, as `clarifier.answer_by_agents: true` allows an agent to write one) SHALL NOT be in force: step
10 SHALL drop it, SHALL record `human.void{question, target, reason}` once for its question, and the hold SHALL be asked
again by the next round.

#### Scenario: SCN-VER-386 (−) The delegate neither answers nor is called
- **Given** the delegate is on and a skipped-test hold is open
- **When** the delegate pass runs
- **Then** no model call is made for the question, it is escalated with the reason `a skipped-test hold is a person's decision`, and the unit stays in `awaiting_human`

#### Scenario: SCN-VER-387 (−) A reply that reaches `check_reply` is refused
- **Given** a delegate reply of `accept` or of `reject` with a `WHEN ... THEN ...` for a verdict question whose target is a skipped-test hold
- **When** `check_reply` runs
- **Then** it returns a discard with status `escalated`

#### Scenario: SCN-VER-388 (−) A model-authored answer is not in force
- **Given** `clarifier.answer_by_agents: true` and an `accept` of the hold recorded with `by: agent`
- **When** step 10 applies the verdicts
- **Then** the hold is unresolved, `human.void` is recorded for the question, the verdict is NEEDS_HUMAN and the next round asks the hold again
- **And** an `accept` with `by: human` is applied

### Requirement: L4-VER-095 A unit in `fixing` whose fix unit waits on a person can be retried
`l4 retry` SHALL be accepted for a unit in phase `fixing` when the open fix unit has at least one pending task and every
pending leaf of it is held by an open question (the planner's `fix unit questions open` state); in any other `fixing`
state it SHALL be refused with exit 2 as before, with the text `the fix unit <name> is running: the harness continues it
at the next run` when a task can run. The retry SHALL record `unit.retried` with `close_fix_unit: <name>` and start a run
as every retry does. In that run, before it selects a task, the harness SHALL, for each pending task of the fix unit,
tick it `already-done` in a harness commit (`L4-TDD: already-done`, `task.done{tdd: "already-done", closed_by: "retry",
reason}`, parents ticked), SHALL set the Status of each open question that held it to `superseded by retry` and record
`question.superseded`, and SHALL then end the fix unit with `fix.done`. A question set so SHALL hold no task, SHALL be
out of `questions.open`, and the label `l4:needs-answers` SHALL go; its text and the fix unit's other files SHALL be kept.
The unit SHALL go to `verifying` and the round SHALL be judged afresh. The fix round the closed unit used SHALL stay
counted. A person's own commit that ticks a task of a fix unit SHALL remain a step 1 blocker (`a protected path was
changed`); it is not a way to close one.

#### Scenario: SCN-VER-389 (+) A retry closes a fix unit that waits on its question and the parent verifies again
- **Given** the pin is the release, `openspec:<name>` is `fixing` with `<name>-fix-2` whose only task 1.1 is held by an open technical question Q-001, and two of three fix rounds are used
- **When** a person runs `l4 retry --unit openspec:<name> --reason "skipped tests are env-gated, see the hold"` and the run starts
- **Then** task 1.1 is ticked in a harness commit with `L4-TDD: already-done`, Q-001's Status is `superseded by retry`, `fix.done` is recorded, and the unit goes to `verifying`
- **And** the new round, judged afresh, has the hold of L4-VER-092 and no finding for the skipped tests, the verdict is NEEDS_HUMAN, and no `-fix-3` is written

#### Scenario: SCN-VER-390 (+) The question no longer blocks anything
- **Given** SCN-VER-389 after the close
- **When** `l4 plan` and `l4 questions list` run
- **Then** neither reports a fix unit question as open, and `l4:needs-answers` is not set for Q-001

#### Scenario: SCN-VER-391 (−) A fix unit that can run is not closed
- **Given** `openspec:<name>` is `fixing` and a task of its open fix unit is not held by any question
- **When** a person runs `l4 retry --unit openspec:<name> --reason TEXT`
- **Then** it exits 2 with `the fix unit <name>-fix-2 is running: the harness continues it at the next run`, and no event is recorded

#### Scenario: SCN-VER-392 (−) A person's tick of the fix unit's task is a blocker, not a way out
- **Given** a person's commit that changes `<name>-fix-2/tasks.md` from `- [ ] 1.1` to `- [x] 1.1`
- **When** the parent is verified
- **Then** step 1 has the blocker `a protected path was changed` naming `<name>-fix-2` and the non-harness commit, as for any person's commit on a fix unit's folder other than `questions.md`

#### Scenario: SCN-VER-393 (−) The same retry on the old harness spends the last fix round
- **Given** the unit's pin is the release before this change
- **When** the verification runs again after any way of closing the fix unit
- **Then** the old finding is raised again as a deterministic major and the round spends the last fix round: this is why the runbook says to upgrade the pin first, and the `l4` of the person is the pin or newer (an older `l4` refuses state-changing commands, L4-OPS-026)
