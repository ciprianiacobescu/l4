## ADDED Requirements

### Requirement: L4-IMP-093 A test the task names can trace a cited criterion, and an unchanged scenario the base tests needs no new test
In the red step (L4-IMP-002, L4-IMP-005), a report id of a test that the task's reviewed text names (L4-IMP-082,
L4-IMP-089) SHALL trace the criteria of its trace like a new test when red changed the test in place (for a Python
test, an id that `names_test_id` maps to it; for another language, an id `named_other_changed` returns), it passed in
the step's base report, it failed at red by assertion (status `failed`, failure kind `assertion`; not an error,
`NotImplementedError` or a hang), its trace (L4-CRT-002) holds one of the unit's criteria, and it traces at most
`verifier.max_criteria_per_test` of the unit's criteria (L4-VER-052). Such a test SHALL count for its criteria's tracing
tests and proof and only there: it SHALL NOT make an id outside the unit's criteria cited, be recorded `test.untraced`
or be listed in `task.red_ok.tests`; a red step whose only tests are such tests SHALL be checked like any red step and
SHALL NOT end as already satisfied. Only a counted test that traces a criterion the step cites SHALL spare the step the `no new test` exit. A red step resumed at green (`resume_red`) SHALL hold each counted test as passing in the base report it rebuilds, so that green must make it pass again. When red fails with `no new test traces <ids>: …` or with `no new test: the test the
task names does not count as a new test: …`, each changed named test that traces one of the step's cited criteria and
does not count SHALL be named after the reason as `; <id>, which the task names, does not count for <criteria>: <why>`,
`<why>` being `it did not pass before this step`, `it hangs at red`, `it does not fail by assertion at red` or `it
traces more than <N> of this unit's criteria`. The red prompt's `# Existing tests this task changes in place` SHALL say
that such a test counts and that the criteria no listed test traces need new tests.

A criterion SHALL be unchanged on the base when the verifier's pass-to-pass rule (L4-VER-009) holds for it (the
archived specs read from git at the unit base, or a Kiro follow-up's merged parent, hold its id with the same text after
`normalise`; red and the verifier SHALL read this through the same helpers) and a test of the step's base report traces
it, passed there and at red, and traces at most `verifier.max_criteria_per_test` of the unit's criteria. A test that red changed in place is no evidence of the base, whatever it asserts now. For a fix unit, the criterion is unchanged on the base only when both the fix unit's reading and its parent's reading of the family are unchanged. In the red step
of any task, fresh or reopened, such a criterion SHALL need no new test: a cited one that no new test traces SHALL be
left out, as L4-OPS-015 leaves out an unchanged criterion of a reopened task. A pre-satisfied candidate (L4-IMP-003)
that is unchanged on the base and that no earlier red confirms SHALL be confirmed by the base specs, without the
zero-value run and the base run, recorded as `criterion.pre_satisfied{via: "unchanged_spec"}` and in
`task.red_ok.criteria` with `proof: "pre_satisfied"`, `discriminating: []`, `via: "unchanged_spec"` and `base_tests`;
it SHALL give no red proof. A task whose every cited criterion is so confirmed SHALL end as already satisfied with no
zero-value and no base run. The judge (L4-VER-018) is shown the criterion's `base_tests` with its new tests, and told that the base specs confirmed it. This confirmation SHALL NOT be made in the task of a fix unit, whose events the judge does not read: such a task keeps the zero-value run, the base run and the hold. A criterion whose text differs from the base specs, that they do not hold, or that no test
of the base traces, passing at the base and at red within the cap, SHALL keep the rules it has.

#### Scenario: SCN-IMP-490 (+) a named TypeScript test changed to fail by assertion is its criterion's red test
- **WHEN** a task's reviewed text names `` `src/registry.test.ts::C-1a2b3c4d the registry lists every tool` ``, which
  passes at the base, its result cites `C-1a2b3c4d`, and red changes that test's expected list so that it fails by
  assertion against the current code and writes no other test
- **THEN** red is accepted: the criterion's proof in `task.red_ok.criteria` names the test's report id,
  `task.red_ok.tests` is empty, `tests.superseded{reason: named_by_task, language: typescript}` names it, the task is
  not already satisfied, and green must make the test pass

#### Scenario: SCN-IMP-491 (+) a named Python test counts beside a new test for another criterion
- **WHEN** a task cites `C-aaaaaaaa` and `C-bbbbbbbb`, its reviewed text names
  `tests/test_registry.py::test_registry_lists_all` (tagged `C-aaaaaaaa`, passing at the base), and red changes that
  test so that it fails by assertion and adds one new failing test tagged `C-bbbbbbbb`
- **THEN** red is accepted, `C-aaaaaaaa` is proved by `tests.test_registry::test_registry_lists_all` and `C-bbbbbbbb`
  by the new test

#### Scenario: SCN-IMP-492 (−) a named test that fails by an error, hangs or failed at the base does not count
- **WHEN** in the task of SCN-IMP-491 red changes the named test so that it fails with `TypeError` (in turn with
  `NotImplementedError`, by the time-out marker, or the test already failed at the base) and adds the new test for
  `C-bbbbbbbb`
- **THEN** the attempt fails with `no new test traces C-aaaaaaaa: ` and the gate's hint, followed by `;
  tests.test_registry::test_registry_lists_all, which the task names, does not count for C-aaaaaaaa: it does not fail
  by assertion at red` (`it hangs at red`, `it did not pass before this step`), and nothing is committed

#### Scenario: SCN-IMP-493 (−) a named test that traces no cited criterion, or too many, does not count
- **WHEN** red changes a named test so that it fails by assertion and writes no other test, and the test traces none of
  the unit's criteria, or in turn four of them under `verifier.max_criteria_per_test: 3`
- **THEN** the first attempt fails with exactly `no new test: the test the task names does not count as a new test: add
  the new test the criterion needs as well`, and the second with that reason followed by `; <id>, which the task names,
  does not count for <criteria>: it traces more than 3 of this unit's criteria`

#### Scenario: SCN-IMP-494 (+) an unchanged scenario that the base already tests needs no new test
- **WHEN** an OpenSpec delta MODIFIES requirement `Registry` and restates its scenario `lists tools` word for word as
  the archived `openspec/specs/registry/spec.md` has it at the unit base, a passing test of the base report traces that
  scenario's id, and a fresh task cites that id and the id of the requirement's new scenario `lists hidden tools`, and
  red adds one new failing test for the new scenario only
- **THEN** red is accepted, the restated scenario needs no test, and nothing is held

#### Scenario: SCN-IMP-495 (+) a passing new test of an unchanged scenario is confirmed by the base specs
- **WHEN** in the unit of SCN-IMP-494, in a project whose tests are not Python, red also adds a new test of the restated
  scenario, which passes at red
- **THEN** the criterion is confirmed with no zero-value and no base run: `criterion.pre_satisfied{via:
  "unchanged_spec"}` names the new test, its record in `task.red_ok.criteria` has `discriminating: []`, `via:
  "unchanged_spec"` and the base tests, the task is not held, and the verifier counts its tests pass-to-pass

#### Scenario: SCN-IMP-496 (+) a task whose every cited criterion is unchanged on the base is already satisfied without a run
- **WHEN** a fresh task cites only restated scenarios that passing base tests trace, and red adds no test, changes no
  file and reports their ids with `tdd_exemption.reason: "already_satisfied by the base"`, or in turn adds one new test
  for each that passes
- **THEN** the step ends as already satisfied (`L4-TDD: already-satisfied`, no green step) with no zero-value and no
  base run, and each criterion has `criterion.pre_satisfied{via: "unchanged_spec"}`

#### Scenario: SCN-IMP-497 (−) a changed scenario is not exempt, even with the same id
- **WHEN** the delta keeps the scenario name `lists tools` but changes its THEN line (the same criterion id, another
  text), or in turn the scenario belongs to an ADDED requirement that no archived spec holds, and red leaves it without
  a new test
- **THEN** the attempt fails with `no new test traces <id>: …`, and a passing new test of it goes to the zero-value run
  and the base run as before

#### Scenario: SCN-IMP-498 (−) an unchanged scenario without a passing base test in the cap is not exempt
- **WHEN** a restated scenario's only tracing test fails in the base report (in turn: it fails at red, it traces four of
  the unit's criteria under `verifier.max_criteria_per_test: 3`, no test traces the scenario, the unit is a Kiro unit
  that is not a follow-up, or `unit_base` finds no base), and red leaves it without a new test
- **THEN** the attempt fails with `no new test traces <id>: …` in each case

## MODIFIED Requirements

### Requirement: L4-IMP-089 (amendment) A changed named test traces a criterion only as L4-IMP-093 says
A changed named test is not a new test. It SHALL trace a cited criterion only as L4-IMP-093 says; a criterion that
neither a new test nor such a named test traces SHALL still fail the attempt (`no new test: the test the task names
does not count as a new test: add the new test the criterion needs as well` when red added no new test, else `no new
test traces <ids>: …`), each followed by L4-IMP-093's note, and a task whose red changed a named test SHALL NOT end as
already satisfied.

#### Scenario: SCN-IMP-440 (−) a changed named test that passes at red, hangs or proves no cited criterion fails the attempt
- **WHEN** red changes the named test of SCN-IMP-439 so that it passes against the current code, or so that it fails by
  a time-out or an error that is not an assertion or `NotImplementedError`, or changes it so that it fails by assertion
  and adds no new test while the test traces none of the criteria the step cites
- **THEN** the attempt fails and the reason names the test (`a test the task names was changed but does not fail at
  red: <id>`, or `no new test: the test the task names does not count as a new test: add the new test the criterion
  needs as well`); the task does not end as already satisfied

### Requirement: L4-IMP-005 (amendment) A Python gate that is not pytest is told the Python name form
For a test gate whose command does not run pytest and names `python`, `manage.py`, `unittest`, `nose2` or `xmlrunner`,
the contract, the red phase, the test chore and the retry message of `check_criteria` SHALL give the id-in-the-name form
with a Python example, `def test_c_xxxxxxxx_…` (an underscore for the dash, which `trace_ids` reads), and SHALL NOT show
`it("C-xxxxxxxx: …")` or `@pytest.mark.l4`.

#### Scenario: SCN-IMP-499 (+) a Python gate that is not pytest is told the Python name form
- **WHEN** the test gate is `uv run python manage.py test` with a JUnit runner, and a red step's new test traces none of
  the criteria it cites
- **THEN** the prompt's contract and the retry message say to put the id in the test's name with an underscore, for
  example `def test_c_xxxxxxxx_…`, and neither shows `it("C-xxxxxxxx: …")` or `@pytest.mark.l4`; a gate that runs
  pytest keeps the marker, and a Vitest gate keeps `it("C-xxxxxxxx: …")`
