## Purpose

Every criterion a Kiro leaf's `_Requirements:_` line names is proved in its red step, by a new test or, when the
leaf is already satisfied, by confirmed existing tests; a step that leaves one out fails and says which.

## MODIFIED Requirements

### Requirement: L4-KSP-003 Criteria and task links of a Kiro unit
Criteria come from `requirements.md` (EARS acceptance criteria, numbered per requirement) or
`bugfix.md` (its `2.n` and `3.n` items; the `1.n` describe the defect); a requirement is `### Requirement N` with `#### Acceptance Criteria`, or `## Requirement N` with `### Acceptance Criteria` (one level higher); a criterion line under that heading may be numbered `1.`, `1)`,
`1.1.`, `1.1)` or `1.1` (in the dotted forms the first number is the requirement's own, and they count only in a
requirement with no plain `N.`/`N)` item, so a `1.1 …` sub-line of a plain criterion stays part of it), with or without
a `-`/`*` bullet; the form never changes the criterion's alias (`Req N.M` by position) or id (L4-CRT-001). When a task
cites a requirement under which no criterion was read, SPEC-002 names the expected form; task→criterion links come from `_Requirements: 2.1, 3.3_` lines, where a number is a reference only when it stands alone (not inside a word such as `ADR-0014.8` or `AC3`), and a reference `2` cites every `2.x` (L4-KSP-006). A leaf task without a requirements
reference MUST be reported by `doctor` (`SPEC-004`) and, under `sdd.enforce`, block intake unless the task kind is
TDD-exempt. The criteria a pending leaf's links name are the criteria its prompt lists with their text (L4-IMP-050) and the criteria its red step must trace (L4-KSP-012, L4-KSP-013); links that name no criterion leave the whole list in the prompt and require none.

#### Scenario: SCN-ODD-02 (−) Kiro leaf without requirement reference
- **GIVEN** leaf `3.1 Add cache` without `_Requirements:_` and not tagged `[chore]`
- **WHEN** intake runs
- **THEN** rejected (14) with reason `task 3.1 cites no requirement`

### Requirement: L4-IMP-003 TDD exemptions and the already-satisfied confirmation
TDD exemptions come only from a **human-written** tag in the task title (`[docs]`, `[config]`,
`[chore]`, `[no-test]`, `[test-infra]`, matching `tdd.exempt_task_kinds`) plus a `tdd_exemption.reason` in the result,
or from harness-generated internal steps (test bootstrap, merge-conflict resolution). Agent claims and file-type
heuristics never create an exemption. The one agent-initiated exemption, `already_satisfied`, is accepted only when
the harness confirms that a discriminating test (L4-VER-009) tracing **every** criterion the step cites exists and
passes. Exemptions are logged (`task.tdd_exempt{kind, reason}`) and listed in `verification.md`. `already_satisfied`
confirmation = the pre-satisfied check of L4-IMP-002 for every cited criterion. For a Kiro leaf, the cited criteria SHALL be the result's `criteria_ids` together with every criterion its `_Requirements:_` line names, less those L4-OPS-015 leaves unchanged (L4-KSP-012, L4-KSP-013). A step that adds new tests may give a
`tdd_exemption.reason` naming the task or commit; the harness proves the claim from the tests and does not require it.
A step that adds no test requires it (below).
**Confirmation by an earlier red.** A cited criterion whose tests already FAILED at an earlier red of the same unit on
this branch is confirmed by that red, without a zero-value run (language-neutral: the zero-value run is Python-only).
It is confirmed when a test T, not one of this step's new tests, traces it, passes at head, is listed by a
`task.red_ok` of the unit's ledger (same `fix_unit` context) among the `discriminating` tests of a criterion proved
`red_assertion` or `zero_value` and by no `criterion.pre_satisfied` of that task (a test the earlier red let pass proves nothing; an
`already-satisfied` event contributes nothing), when that red's `base` and its commit (the `sha` of the
`task.red_committed` with the same task and base) are ancestors of `HEAD` (a rebase voids it), and when T's file is
has only gained lines since that commit, in later commits and in this step alike (a task may be told to add its tests
to an earlier task's file; a changed or deleted line voids the evidence). T's file is the part of its id before `::`
when that path exists in the red commit, else the longest dotted prefix of it that names a `.py` file there, so the
class of `pkg.tests.test_x.TestY::test_z` does not hide `pkg/tests/test_x.py`. Only the criteria so
confirmed skip the zero-value run; the rest go through it. The proof is `pre_satisfied` with `discriminating` = the
earlier tests, `via: earlier_red`, `red_sha` and `red_task` of the newest such red; `criterion.pre_satisfied` carries
`via` too. On success the harness commits the tests as
`test(<unit>): <task> already satisfied` with `L4-TDD: already-satisfied`, flips the marker and skips green (its `task.red_ok` carries `tdd: already-satisfied` and the console says
`task <key> already satisfied: N new test(s) pass on the base, no green step`)
[V, spikes/02, 2/2 live; this makes SCN-IMP-13 operational, it is not a new path]. The `[chore]` task of a rejected
coverage hold is a harness-made exemption too, and its step adds tests (L4-VER-006).
**Confirmation by a base run.** The order is: the earlier red, then the zero-value run on the criteria left, then a
base run on the criteria the zero-value run left unconfirmed (a project it cannot read, or a criterion it could not
decide); when the zero-value run confirms everything, no base run happens. A base run (`implementer/base_run.py`,
language-neutral) runs the test gate as `test-base-run` against the unit base code (`unit_base`): the production files
changed since the unit base, by commits or in the worktree (a red stub), are swapped to their base content (`git
diff base HEAD` plus the worktree's changes; files added since are set aside), while test files, test support files and
harness, spec and documentation paths (evidence kind `exempt`) stay as the worktree holds them. If any dependency
manifest or lock file (`package.json`, lock files, `pyproject.toml`, `requirements*.txt`, `*.csproj`, `*.sln`,
`Directory.Build.*`, `Directory.Packages.props`, `global.json`, `NuGet.config`, `go.mod`, `Cargo.*`, ...) or any
`tdd.runner_config_files` file changed since the unit base, the environment differs: the run is skipped and nothing is
confirmed. A symlink or submodule in the changed set skips it too. Every file touched is put back byte for byte (sha256
checked) before anything else runs. A criterion is confirmed only when one of its new tests FAILS BY ASSERTION in that
run; an error (missing export, import or collection error, TypeError) is inconclusive, and a test that passes at the
unit base too shows the criterion was satisfied before the unit: not confirmed. The step then fails with `not
discriminating: ` naming only the criteria neither run confirmed. The proof is `pre_satisfied` with `discriminating` =
the tests that failed at the base, `via: base_run` and `base_sha`; `criterion.pre_satisfied` carries `via` too.
**Already satisfied without a new test.** When an earlier task already wrote and proved the tests of every criterion a
task cites, a copy proves nothing more. A red step that adds no new test, changes no file and adds no stub is accepted
as already satisfied when its result reports `criteria_ids` and a `tdd_exemption.reason` that starts with
`already_satisfied`, and every cited criterion is the unit's and is confirmed. The candidates of a criterion are the
tests of the head report that trace it and pass, and they go through the same order: the earlier red, the zero-value
run, the base run. The harness then ticks the task and commits `test(<unit>): <task> already satisfied` with
`L4-TDD: already-satisfied`, holding no test change. The proofs are `pre_satisfied` with `tests: []` and the confirmed
tests as `discriminating`, and no green step runs. The console says `task <key> already satisfied by existing tests, no
green step`. A cited criterion that no passing test traces fails the step with `no test traces <ids> yet: write a new
test for each`. One that nothing confirms fails it with `not discriminating: `, as above. A step that adds no test
without that reason or without `criteria_ids` fails as before (L4-IMP-002): `no tests added`, or `no new test` when it
touched a test file. `already_satisfied` needs the
task's own text to be true in the code: a task that asks for a change that is not there yet (a document line, say) is
not already satisfied, whatever its criteria say, and the judge checks each such task against its text (L4-VER-018).

#### Scenario: SCN-IMP-207 (+) An already-satisfied task adds no test and reuses the earlier ones
- **GIVEN** task 1.1's red wrote a test tracing criterion C that failed by assertion, and green made it pass
- **WHEN** task 2.1's red step adds no test, changes no file, and reports `criteria_ids: [C]` and
  `tdd_exemption.reason: "already_satisfied by 1.1"`
- **THEN** C is confirmed `via: earlier_red` by 1.1's test, the task is committed as `already satisfied` with no test
  file in the commit, its proof is `{tests: [], proof: pre_satisfied, discriminating: [1.1's test], via: earlier_red}`,
  and no green step runs

## ADDED Requirements

### Requirement: L4-KSP-012 Red covers every criterion a Kiro leaf cites
In the red step of a Kiro leaf, each criterion of its own unit that its `_Requirements:_` line names SHALL count as
cited and SHALL be traced by a new test, unless L4-OPS-015 leaves it unchanged or an earlier red proved it with tests
that pass now (per criterion and test, in a test file since only appended to). A step that leaves one untraced SHALL
fail with a reason naming its id, alias and line. A red step MAY append tests to an existing test file, not a
computed constant (SCN-KSP-007).

#### Scenario: SCN-IMP-294 (−) A red step that leaves a cited criterion untested is rejected with the reason
- **GIVEN** a Kiro leaf `1. Implement the tip function` with `_Requirements: 1.1, 1.2_`, and a red step whose one new
  test traces only `Req 1.1` and that reports only that criterion's id in `criteria_ids`
- **WHEN** the red step is checked
- **THEN** it fails with `no new test traces <id of Req 1.2> (Req 1.2), which the task's _Requirements: 1.1, 1.2_
  line names: write a new test for each criterion that line names, tagged with its id`, and nothing is committed
- **AND** the prompt of the next red attempt holds that reason under `# Your previous attempt was rejected`

#### Scenario: SCN-IMP-295 (+) An unchanged criterion needs no new test, and an earlier-proved one is confirmed
- **GIVEN** (a) the leaf of SCN-IMP-294 reopened by a spec edit that changed `Req 1.2` only (L4-OPS-015), (b) the
  same leaf when task 0.9's red already proved `Req 1.1` with tests that pass now, and (c) a fix unit's leaf citing `2.1`, the item that
  restates the parent's `Req 1.2`, in a parent that also has a `Req 2.1` of its own
- **WHEN** (a) a red step adds a failing test for `Req 1.2` only, (b) a red step adds a failing test for `Req 1.2`
  only, or also a new test for `Req 1.1` that passes at once, and (c) the fix leaf's red step is checked
- **THEN** (a) is committed as red with no test for `Req 1.1` required
- **AND** (b) is committed as red in both cases, with `Req 1.1` proved `pre_satisfied` `via: earlier_red` (by the
  earlier tests, no copy needed) and `Req 1.2` proved by its failing test
- **AND** (c) requires only the restated criterion's id, never the parent's own `Req 2.1`, and its prompt lists only
  that criterion

### Requirement: L4-KSP-013 An already-satisfied Kiro leaf proves every criterion it cites
A red step of a Kiro leaf that adds no test SHALL be accepted as already satisfied only when every criterion its
`_Requirements:_` line names, together with those `criteria_ids` lists, is traced by passing tests that the harness
confirms (earlier red, zero-value run, base run). A named criterion that no passing test traces SHALL fail the step
with `no test traces <id> yet: write a new test for each`, and the task SHALL NOT be ticked.

#### Scenario: SCN-IMP-296 (−) The no-new-test path refuses a leaf whose cited criterion no test traces
- **GIVEN** the leaf of SCN-IMP-294, task 0.9's red that proved `Req 1.1`, no test that traces `Req 1.2`, and a red
  step that adds no test, changes no file and reports `criteria_ids: [<id of Req 1.1>]` and `tdd_exemption.reason:
  "already_satisfied by 0.9"`
- **WHEN** the red step is checked
- **THEN** it fails with `no test traces <id of Req 1.2> yet: write a new test for each`, the leaf stays `[ ]`, and
  nothing is committed

#### Scenario: SCN-IMP-297 (+) A leaf whose cited criteria are all proved is already satisfied
- **GIVEN** the leaf of SCN-IMP-294, earlier reds that proved `Req 1.1` and `Req 1.2`, and a red step that adds no
  test and reports only `Req 1.1`'s id with `already_satisfied by 0.9`
- **WHEN** the red step is checked
- **THEN** both criteria are confirmed `via: earlier_red`, the leaf is committed `already satisfied`, and
  `task.red_ok.criteria` holds a `pre_satisfied` proof for each of them

#### Scenario: SCN-KSP-006 (−) A tag added to an earlier test proves nothing for the new criterion
- **GIVEN** task 0.9's red proved `Req 1.1` only, and the leaf of SCN-IMP-294 whose step adds a passing copy for `Req
  1.1` and inserts `@pytest.mark.l4(<Req 1.2>)` above 0.9's test
- **WHEN** the red step is checked
- **THEN** it fails with `no new test traces <id of Req 1.2> (Req 1.2), which the task's _Requirements: …`, because the
  proof of an earlier red holds for the criterion and the tests it listed, and nothing is committed

#### Scenario: SCN-KSP-007 (+) New tests and fixtures may go into an existing test file; a computed constant may not
- **GIVEN** an existing project test file and a red step that adds to it a fixture, a parametrized test with `Decimal`
  cases that are literals, a method of its test class or a merged import name, beside the new tests of the leaf; or a
  module constant computed by a call (`TEN = Decimal("10")`) or a parametrize case that calls at import
- **WHEN** the red step is checked, on a Kiro unit and on an OpenSpec unit
- **THEN** the first is committed as red; the second is refused with `red changed tests that existed before this step`
  (`<module>`), and the retry text says to compute the value inside the new test or to put the new tests in a new
  file; only an earlier red's proof for a test file that was not only appended to (a Python
  file) or lost a line (any other file) is voided, and the criterion then needs a new test

#### Scenario: SCN-KSP-008 (+) A step that lists every cited id is accepted when an earlier red proved one
- **GIVEN** task 0.9's red proved `Req 1.1`, and a red step that adds a failing test for `Req 1.2` and reports both ids
  in `criteria_ids`, as the result schema says
- **WHEN** the red step is checked
- **THEN** it is committed as red, with `Req 1.1` proved `via: earlier_red`
