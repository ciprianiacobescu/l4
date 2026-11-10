## MODIFIED Requirements

### Requirement: L4-VER-067 (amendment, a covered criterion the writer cannot test is a note)
A UI criterion that step 4 covers with a discriminating test, and for which the writer returns `not_testable`, SHALL be
a note and SHALL NOT be a hold. Step 4 covers it so when its evidence in the round's trace (`VerifyResult.trace`) as it
stands when step 5 starts (step 4's trace with step 4a's audit tests and holds) has the state `covered`, no `held`
reason, and at least one tracing test that passed, is adequate, is within the per-test cap and has a proof that a run
showed: any proof but `pass_to_pass`, and no label of a red record that no run proved (`not applicable: no project
code`, or an accept after an inconclusive check, L4-VER-051). Step 5 SHALL take this answer from that trace, with no
gate run and no ledger read, and SHALL store it on the criterion's outcome: `verify.generated{status: not_testable,
covered_by: [<the covering test ids>]}` and `covered_by` in `verdict.json`. The criterion's row of the generated UI
tests table SHALL keep the status `not_testable` and the writer's reason and SHALL add `covered by step 4: <ids>; a
note, not a hold (L4-VER-067)`; step 5's note SHALL count the notes; no hold SHALL be raised for it, its minor gap
finding SHALL stay, and no fix unit SHALL be made for that finding (the gap is closed, as a waived gap is). A round whose
steps are reused (`reused (round N)`) SHALL keep the stored outcomes and holds and SHALL NOT decide a note again from the
stored trace, which carries step 9's adequacy; a stored outcome with no `covered_by` (written before this change) is
restored with none. The hold SHALL stay when nothing discriminating traces the criterion (only `pass_to_pass` tests,
only red records that no run proved, a failing tracing test, a failed audit test, or no tracing test), for every other
outcome of the writer (`writer_failed`, `uncollectable`, `fails_at_head`, `non_discriminating`, `base_error`,
`base_unservable`, `lint_failed`), covered or not, and when no writer is configured. A note SHALL NOT pass the criterion:
it still needs an adequate passing test and the judge's pass (L4-VER-003), so a covering test that the judge calls
inadequate leaves the criterion `needs_human`, asked through its own verdict question. Which criteria are UI-facing
(L4-VER-014), which UI criteria are gaps, and the waiver above SHALL be unchanged.

#### Scenario: SCN-VER-298 (+) a UI criterion that step 4 covers and the writer cannot test is a note
- **WHEN** a unit that changed one file under `verifier.playwright.ui_paths` has ten criteria, eight of them covered by
  red-proved tests (`zero_value`) and two with no tracing test, and the writer returns `not_testable` for all ten
- **THEN** the eight record `verify.generated{status: not_testable, covered_by: [<their tests>]}` and raise no hold,
  their rows of the generated UI tests table read `not_testable` with the writer's reason and `covered by step 4: …; a
  note, not a hold (L4-VER-067)`, step 5's note counts eight notes, the two uncovered criteria raise their UI holds,
  and the round asks two UI hold questions in place of ten

#### Scenario: SCN-VER-299 (−) a criterion that nothing discriminating traces keeps its hold
- **WHEN** the writer returns `not_testable` for a UI criterion whose only tracing tests are `pass_to_pass`, or whose red
  record no run proved (`not applicable: no project code`, or an accept after an inconclusive check), or whose tracing
  test fails, or whose audit test fails at head, or that no test traces
- **THEN** the outcome has no `covered_by` and the criterion's UI hold is raised as before

#### Scenario: SCN-VER-300 (−) a covered criterion keeps its hold when generation failed in another way
- **WHEN** step 4 covers a UI criterion with a red-proved test and the writer's outcome is `writer_failed`,
  `uncollectable`, `fails_at_head`, `non_discriminating`, `base_error`, `base_unservable` or `lint_failed`, or
  `roles.verifier_agent` is empty
- **THEN** the criterion's UI hold is raised as before, and no outcome has `covered_by`

#### Scenario: SCN-VER-301 (+) a reused round keeps the note and raises no hold
- **WHEN** round 1 noted C-1 and held C-2, ended `NEEDS_HUMAN`, a person accepted C-2's hold, and the next run reuses
  round 1 (steps `reused (round 1)`)
- **THEN** no writer is called, C-1's row still has its `covered_by`, no hold is raised for C-1 whatever the stored
  trace's adequacy says, and the unit can pass; a `verdict.json` written before this change restores its outcomes with
  no `covered_by` and its holds as stored

#### Scenario: SCN-VER-302 (+) a noted gap is closed for the fix-unit planner, and its finding stays
- **WHEN** a PASS round under `verifier.fix_minor_findings: true` has a noted criterion with its minor finding `UI
  criterion without an end-to-end test`
- **THEN** the finding is listed with the round's findings and no fix unit is made for it

#### Scenario: SCN-VER-303 (−) a note does not pass the criterion
- **WHEN** a noted criterion's only covering test is called inadequate by the judge
- **THEN** the criterion is `needs_human` (`uncovered: the tests that trace it are inadequate or did not pass`), one
  verdict question asks about the criterion, and no UI hold is raised for it

## ADDED Requirements

### Requirement: L4-VER-077 The UI test writer is shown the e2e suite's support files
When step 5 asks the writer for a test, its prompt SHALL hold, after the page snapshot, the e2e suite's support files as
they are at the merge base: `e2e/conftest.py` and every other `.py` file under `e2e/` that is a regular file (no link,
no submodule), whose name is not a test module's (`test_*.py`, `*_test.py`, so never the harness's
`test_l4_c_<hex>.py`), that is not a `conftest.py` below `e2e/`, has no path part that starts with `.` or is
`__pycache__` or `node_modules`, and is not empty. They SHALL be taken in that order (`e2e/conftest.py`, then the others by
depth and path), each cut at 8,000 characters with its label saying so, until six are taken or the next would bring the
total past 20,000 characters; that file and every file after it SHALL be left out and named in one more block. They SHALL be read from the merge base only, because the
generated test runs at the base and, at head, with the e2e runner's support files the unit changed at their base
versions (L4-VER-035): a helper the unit added is not shown. The writer's e2e rules SHALL say that its test runs with the
files shown, to use their fixtures by parameter name and import their helpers from the module that defines them, and to
use no name they do not define; the template version SHALL be `testwriter@6`. Step 5's note SHALL say how many files
were shown and how many were left out. A project with no such file SHALL get no block, and no configuration key SHALL
be added.

#### Scenario: SCN-VER-304 (+) the writer is shown the e2e suite's support files at the merge base
- **WHEN** the base has `e2e/conftest.py` with a `login` helper and a `users` fixture, `e2e/helpers/a11y.py` and the
  test module `e2e/test_sign_in.py`, and the unit changed `e2e/conftest.py`
- **THEN** the writer's prompt holds, after the page snapshot, `e2e/conftest.py` as it is at the base (not the unit's
  version) and then `e2e/helpers/a11y.py`, and not `e2e/test_sign_in.py`; its e2e rules say to use the shown fixtures
  and import the shown helpers; the prompt's template is `testwriter@6`; step 5's note says two files were shown

#### Scenario: SCN-VER-305 (−) the support files shown are bounded and the rest are named
- **WHEN** the base has an `e2e/conftest.py` of 30,000 characters and nine helper files under `e2e/` of 5,000
  characters each; or eight helper files of 1,000 characters each
- **THEN** in the first case the prompt holds `e2e/conftest.py` cut at 8,000 characters, its label saying so, and the
  first two helpers by path (18,000 characters), and the block `e2e support files not shown` lists the other seven; in
  the second it holds six helpers and lists two; step 5's note gives both counts

#### Scenario: SCN-VER-306 (−) what is not a support file of the suite is not shown
- **WHEN** the only `.py` files under `e2e/` at the base are test modules, a link, an empty `__init__.py`, a file under
  `e2e/.venv/` and `e2e/admin/conftest.py`, and the unit added `e2e/helpers.py`
- **THEN** the prompt holds no support-file block, and the rest of the prompt is as before this change apart from the
  e2e rules
