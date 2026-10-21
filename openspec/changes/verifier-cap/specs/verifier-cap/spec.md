## Purpose

The per-test cap (`verifier.max_criteria_per_test`) is a rule the implementer reads when it tags tests and that a red
step meets when it writes them, not one it first meets at verification. No harness text advises an id past the cap. A
proved, passing test over the cap counts for a criterion only when the judge passed that criterion and named that test
for it with a `test_adequacy` entry, and never when the test traces more than `min(half of the unit, 3 × the cap)`. When
the cap alone leaves a criterion uncovered, its question says so and names the fix.

## ADDED Requirements

### Requirement: L4-VER-052 The per-test cap is stated and checked when a test is written
The implementer's harness contract SHALL state the cap with its configured value next to the tagging rule, in every
role's prompt: `A test that traces more than <N> of this unit's criteria counts for none of them
(verifier.max_criteria_per_test), and the harness rejects a red step or test chore that writes one: give each test one
behaviour and at most <N> ids, tag a test only with the criteria whose outcome it asserts, put a criterion that many
tests touch (a precondition, or a list of commands) only on the tests that assert it directly, and write another test
rather than add an id to a test that has <N>.`, where `<N>` is `verifier.max_criteria_per_test`. The red phase SHALL say
that a `_Requirements:_` line that names K criteria needs at least ⌈K/<N>⌉ tests, and that a test may carry a
zero-answer criterion as well only when it then carries at most `<N>` ids. A red step SHALL fail its attempt, before the
pre-satisfied, base and zero-value runs, when one of its new tests traces more than `<N>` of the unit's criteria (the
criteria the verifier traces for the unit; other ids do not count), with this text: `too many criteria on one test:
<test> traces <n> of this unit's criteria (<ids>), more than verifier.max_criteria_per_test (<N>), so the verifier
counts it for none of them: split it into tests that each assert one behaviour and carry at most <N> ids, and tag a test
only with the criteria whose outcome it asserts`, naming at most three tests (then `(+k more)`). A test chore SHALL fail
its attempt with the same text when one of its added tests does, before its discrimination runs. Tests that existed
before the step MUST NOT be checked. The contract's template version SHALL be 13 and the red template's 12.

#### Scenario: SCN-VER-170 (+) Every prompt states the cap with its value
- **GIVEN** a unit with `verifier.max_criteria_per_test` unset (3), and in turn `2`, under a pytest gate and under a
  Vitest gate
- **WHEN** the red, green, single and test-chore prompts are rendered
- **THEN** each holds `counts for none of them (verifier.max_criteria_per_test)` and `at most 3 ids` (`at most 2 ids`
  with `2`); the red prompt holds `needs at least ⌈K/3⌉ tests` (`⌈K/2⌉` with `2`) and `when that test then carries at most 3 ids`; the template
  versions read `contract@13+red@12`, `contract@13+green@5`, `contract@13+single@3` and `contract@13+single_tests@5`

#### Scenario: SCN-VER-171 (−) A red step that writes a test over the cap fails its attempt
- **GIVEN** a unit with 8 criteria and a red step whose new test `tests/test_cart.py::test_flow` traces 5 of them, and a
  second new test that traces 1
- **WHEN** the harness checks the step
- **THEN** the attempt fails with `too many criteria on one test: tests/test_cart.py::test_flow traces 5 of this unit's
  criteria (…), more than verifier.max_criteria_per_test (3), so the verifier counts it for none of them: split it into
  tests that each assert one behaviour and carry at most 3 ids, and tag a test only with the criteria whose outcome it
  asserts`; the changes are discarded; no zero-value, base or pre-satisfied run was made; and the next attempt's prompt
  carries the text as its previous failure

#### Scenario: SCN-VER-172 (+) A test at the cap passes, and ids of another unit do not count
- **GIVEN** a red step whose new tests trace 3 of the unit's criteria each, one of them also tagged with two ids that
  are not the unit's criteria; and in turn a unit with `verifier.max_criteria_per_test: 5` and a new test that traces 5
- **WHEN** the harness checks the step
- **THEN** the cap check passes in both, and the step goes on to its discrimination runs

#### Scenario: SCN-VER-173 (−) A test chore's added test over the cap fails the chore
- **GIVEN** a test chore whose added, passing test traces 4 of the unit's criteria
- **WHEN** the harness checks the chore
- **THEN** the attempt fails with the text of SCN-VER-171 for that test, before any discrimination run, and no
  `task.tests_added` is recorded

#### Scenario: SCN-VER-174 (+) Tests written before the step are not checked
- **GIVEN** a unit whose earlier task committed a test that traces 5 of its criteria, and a red step of the next task
  whose new tests trace at most 3 each
- **WHEN** the harness checks the step
- **THEN** the cap check passes; the earlier test is left to step 4

### Requirement: L4-VER-053 The red remedies respect the cap
The red phase's zero-answer remedy (a criterion whose tests pass or error against the zero-value stubs, L4-IMP-002)
SHALL propose tagging the criterion on a test of the attempt that failed on the zero values only when that test traces
fewer than `verifier.max_criteria_per_test` of the unit's criteria and not the criterion itself. The example SHALL show
that test's whole list of the unit's ids plus the criterion, in the gate's own form (`@pytest.mark.l4("<id>", …)` for a
pytest gate, `it("<id> <id>: …")` otherwise). When no such test has room, the remedy SHALL say instead `, or write a
new test that asserts a real answer and tag it with <criterion> alone (every test that failed on the zero values
already carries <N> ids)`. No retry text of the harness MAY advise adding an id that puts a test over the cap.

#### Scenario: SCN-VER-175 (−) The remedy never advises a full test
- **GIVEN** a vacuous criterion `C-zzzzzzzz` whose scenario's answer is 0, and the attempt's only test that failed on
  the zero values traces 3 of the unit's criteria
- **WHEN** the vacuity message is written
- **THEN** it says `write a new test that asserts a real answer and tag it with C-zzzzzzzz alone (every test that
  failed on the zero values already carries 3 ids)` and does not say `as well`

#### Scenario: SCN-VER-176 (+) The remedy names a test with room, with all its ids
- **GIVEN** the criterion of SCN-VER-175, a proved test `t::full` with 3 ids and a proved test `t::room` with the ids
  `C-aaaaaaaa` and `C-bbbbbbbb`, under a pytest gate
- **WHEN** the vacuity message is written
- **THEN** it says `tag a test that asserts a real answer with C-zzzzzzzz as well, for example t::room:
  @pytest.mark.l4("C-aaaaaaaa", "C-bbbbbbbb", "C-zzzzzzzz")` and does not name `t::full`

#### Scenario: SCN-VER-177 (+) The remedy uses the gate's form
- **GIVEN** the case of SCN-VER-176 under a gate that runs `npx vitest run`
- **WHEN** the vacuity message is written
- **THEN** the example is `it("C-aaaaaaaa C-bbbbbbbb C-zzzzzzzz: …")` and holds no `@pytest.mark.l4`

### Requirement: L4-VER-054 A proved test over the cap counts when the judge named it for the criterion
Step 4 SHALL keep, for each criterion, every test over the cap that has a proof for it under L4-VER-009 (the cap aside)
and passed, as a candidate with the number of the unit's criteria it traces; such a test SHALL stay ignored with its
reason and its minor finding. A test with no proof, or skipped, MUST NOT be a candidate. The judge's traceability lines
SHALL list a criterion's candidates as `over the per-test cap: <test> (traces <n> criteria)` (at most five, then `(+k
more)`), and its system text SHALL say that such a test counts for that criterion only when the judge passes the
criterion and gives a `test_adequacy` entry for that test and that criterion with `adequate: true`, and ask for one
entry, true or false, per candidate it read, and say that the evidence of its pass alone does not count; the judge
prompt version SHALL be 12. After the judge's reply, where its `test_adequacy` is applied, a candidate SHALL become a
tracing test of the criterion, keeping its proof, when all hold: the judge's verdict for the criterion is `pass`; the
judge named the test for it, by a `test_adequacy` entry with `adequate: true` for that test and that criterion, whose
reason does not start with `not in this part` (a part of a diff judged in parts that never saw the test cannot name it);
a `test` evidence item of the criterion's pass is not enough on its own; no `test_adequacy` entry with `adequate: false`
names that test with that criterion or with no criterion; and the test traces at most `min(M // 2, 3 × N)` of the unit's
criteria (M the unit's criteria, N the cap; the 3 is not configurable). An `uncovered` criterion is then `covered` (a
`fail` stays `fail`), the test leaves its ignored list, and `verification.md` labels it `over the per-test cap: traces
<n> criteria, named by the judge`. No other candidate SHALL count. `verdict.json` SHALL record the candidates and the
label in the round's trace, and a round resumed at aggregation SHALL read them back, with the labels of L4-VER-051; a
record without them SHALL load with no candidates.

#### Scenario: SCN-VER-178 (+) A judge-named test over the cap covers its criterion
- **GIVEN** a unit with 12 criteria, a passing test `t::flow` that traces 5 of them, `C-aaaaaaaa` among them, and a
  `task.red_ok` that proves `C-aaaaaaaa` with it; the judge passes `C-aaaaaaaa` and answers `test_adequacy: [{test:
  t::flow, criterion: C-aaaaaaaa, adequate: true}]`
- **WHEN** the round aggregates
- **THEN** `C-aaaaaaaa` is `covered` and `pass`, `verification.md` shows `t::flow (passed, red_assertion, over the
  per-test cap: traces 5 criteria, named by the judge)`, and the minor finding `a test is ignored as evidence` of step 4
  is still listed

#### Scenario: SCN-VER-179 (−) A test that only the judge's pass cites does not count
- **GIVEN** the unit of SCN-VER-178, and a judge that passes `C-aaaaaaaa` with the evidence `{kind: test, ref: t::flow}`
  and gives no `test_adequacy` entry for `t::flow`
- **WHEN** the round aggregates
- **THEN** `C-aaaaaaaa` stays `uncovered` (`needs_human`) with the reason of L4-VER-055 (`; the judge did not confirm it
  for this criterion`); the same judge with the entry `{test: t::flow, criterion: C-aaaaaaaa, adequate: true}` covers it

#### Scenario: SCN-VER-180 (−) A test tagged with every criterion, or with more than the ceiling, is no evidence, whatever the judge says
- **GIVEN** a unit with 5 criteria, one passing test tagged with all 5 and proved for each, and a judge that passes all
  5 and marks the test adequate for each; and in turn a unit with 29 criteria and a test that traces 15 of them, and one
  that traces 10 of them (the ceiling there is min(29 // 2, 3 × 3) = 9), judged the same way
- **WHEN** the round aggregates
- **THEN** the test is evidence for none of them, every criterion it traces stays `uncovered` (`needs_human`), and the
  minor finding records the over-tagged test

#### Scenario: SCN-VER-181 (−) The judge's doubt wins, and a part that never saw the test names nothing
- **GIVEN** the test of SCN-VER-178, which also traces `C-bbbbbbbb` and `C-cccccccc`; the judge passes `C-aaaaaaaa` and
  `C-bbbbbbbb`, names the test adequate for `C-aaaaaaaa`, answers `{test: t::flow, criterion: C-bbbbbbbb, adequate:
  false}`, and fails `C-cccccccc` citing the test; and in turn a diff judged in two parts, where the part that does not
  hold `t::flow` passes `C-aaaaaaaa` and answers `{test: t::flow, criterion: C-aaaaaaaa, adequate: false, reason: "not
  in this part"}` (the merge turns it into `adequate: true`) and the part that holds the test gives no entry for it
- **WHEN** the round aggregates
- **THEN** only `C-aaaaaaaa` is covered; `C-bbbbbbbb` and `C-cccccccc` stay `uncovered`; with `{test: t::flow,
  criterion: "", adequate: false}` instead, none of the three is covered; in the parts case `C-aaaaaaaa` stays
  `uncovered`, because a part that never saw the test cannot name it

#### Scenario: SCN-VER-182 (−) No proof, no candidate
- **GIVEN** a passing test over the cap that traces `C-aaaaaaaa` and has no red, audit, generated, extra or
  pass-to-pass proof for it, and a judge that passes `C-aaaaaaaa` and names the test adequate
- **WHEN** the round aggregates
- **THEN** the test is not a candidate and `C-aaaaaaaa` stays `uncovered`; its ignored reason is the cap's, as today

#### Scenario: SCN-VER-183 (+) The judge sees the candidates
- **GIVEN** the unit of SCN-VER-178 before the judge
- **WHEN** the judge prompt is built
- **THEN** its version is `judge@12`, the traceability line of `C-aaaaaaaa` reads `C-aaaaaaaa  uncovered  no
  discriminating test; over the per-test cap: t::flow (traces 5 criteria)`, and the system text holds the rule on such a
  test; a criterion with seven candidates lists five and `(+2 more)`

#### Scenario: SCN-VER-184 (+) A resumed round keeps what the judge named
- **GIVEN** the round of SCN-VER-178 ending NEEDS_HUMAN on another criterion, a person's answer to that question, and a
  second stored round of an older harness whose trace has no `capped` key
- **WHEN** each next round resumes at aggregation
- **THEN** the first keeps `C-aaaaaaaa` covered with its label and the L4-VER-051 labels of its tests; the second loads,
  has no candidates and counts nothing over the cap

### Requirement: L4-VER-055 A criterion that only the cap left uncovered says so
When a criterion has no usable tracing test and no passing test within the cap, the judge's verdict for it is `pass`,
and it has a candidate of L4-VER-054 that was not counted, its outcome reason SHALL be `uncovered: the judge passed it, and only the per-test cap left it
uncovered: <test> traces <n> criteria, more than verifier.max_criteria_per_test (<N>)<why>`, with `<why>` `; it traces
more than <C> of the unit's <M> criteria, the most the judge can make count` when it does (<C> is `min(M // 2, 3 × N)`),
else `; the judge did not confirm it for this criterion` (not named, or named inadequate), for the candidate with the
fewest criteria (then by id), followed by `(+k more)` when there are more. Its verdict question SHALL show that reason
and, before the answer line, `Fix: answer accept if <test> checks this criterion as its scenario says; or reject: give
it its own test of at most <N> ids (a reject fails the criterion and spends a fix round).` A criterion the judge did not pass, one with no candidate, or one that a passing test within the cap traces (the judge called that test inadequate, so the cap is not why it is uncovered) SHALL keep today's reason and question.

#### Scenario: SCN-VER-185 (−) The question says the judge passed it and names the fix
- **GIVEN** a unit with 29 criteria, a criterion `C-dddddddd` whose only test `t::missing` traces 7 of them, is proved
  and passed, and a judge that passes `C-dddddddd` with a file quote only
- **WHEN** the round raises its questions
- **THEN** the criterion is `needs_human` with `uncovered: the judge passed it, and only the per-test cap left it
  uncovered: t::missing traces 7 criteria, more than verifier.max_criteria_per_test (3); the judge did not confirm it
  for this criterion`, and its question holds that line and `Fix: answer accept if t::missing checks this criterion as
  its scenario says; or reject: give it its own test of at most 3 ids (a reject fails the criterion and spends a fix round).`

#### Scenario: SCN-VER-186 (−) A candidate over the ceiling says so
- **GIVEN** a unit with 8 criteria, a criterion whose only proved, passing test traces 5 of them, and a judge that
  passes it and names the test adequate
- **WHEN** the round aggregates
- **THEN** the criterion stays `needs_human`, and its reason ends `; it traces more than 4 of the unit's 8 criteria, the most the judge can make count`

#### Scenario: SCN-VER-187 (+) A criterion the judge did not pass keeps today's text
- **GIVEN** the criterion of SCN-VER-185 failed by the judge, in turn passed by the judge with no candidate, and in turn passed by the judge with a candidate and also a passing test within the cap that the judge called inadequate for it
- **WHEN** the round raises its questions
- **THEN** the reason is `uncovered: no adequate discriminating test traces it` in the first two and `uncovered: the tests that trace it are inadequate or did not pass` in the third, and the question holds no `Fix:
  answer accept if` line; the third also keeps the cap out of its reason

#### Scenario: SCN-VER-188 (+) A round like the incident asks three criterion questions, not eleven
- **GIVEN** a unit with 29 criteria, 18 covered by tests within the cap, and 11 traced only by proved, passing tests
  that trace 5 to 7 criteria each; a judge that passes the 18 and 10 of the 11, gives a `test_adequacy` entry with
  `adequate: true` for the criterion's over-cap test for 8 of those 10, cites the test in the evidence of its pass only
  for one and a file for the other, and fails the eleventh, naming its test inadequate for it
- **WHEN** the round aggregates and raises its questions
- **THEN** 26 criteria pass; the 2 criteria without an entry are `needs_human` with the reason of L4-VER-055; the
  eleventh is `needs_human` with `uncovered: no adequate discriminating test traces it`; and three criterion questions
  are raised (the forecast depends on the judge following judge@12: each missing entry is one more question of
  L4-VER-055)

#### Scenario: SCN-VER-189 (+) One configured cap for the prompt, the red check and step 4
- **GIVEN** `verifier.max_criteria_per_test: 4` and a red step whose new test traces 4 of the unit's criteria
- **WHEN** the prompt is rendered, the step is checked and the unit is verified
- **THEN** the prompt says `at most 4 ids`, the red check passes, and step 4 counts the test as evidence for each of
  the 4 criteria it proves; a new test that traces 5 fails the red check
