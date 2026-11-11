## MODIFIED Requirements

### Requirement: L4-IMP-002 (amendment, where the static gates run)
Check 6 of the red phase (static gates) SHALL run where L4-IMP-096 places it: once per step: before the pre-satisfied
confirmation when it has candidates, before the base run and before run (b), else after check 5. Item (c) of the green phase (lint/typecheck) SHALL run, when (b)
gave no failure, before the test-at-red run of corrected tests (L4-IMP-063). The rules of both are otherwise unchanged:
a gate that passed at the step base MUST pass, a gate that already failed there is recorded as
`gate.static_baseline_failed` and does not fail the step, and a red failure feeds the redacted, truncated gate output
back to the retry.

#### Scenario: SCN-IMP-524 (+) A step without a variant run keeps the order, and the static gates run once
- **Given** a red step whose new tests fail by assertion and that adds no stub, so it makes no variant run, and a red
  step whose passing new tests go to the base run and are confirmed there
- **When** each is checked
- **Then** the first runs its static gates after its red verdict, as before, and fails on a red check before them when
  it has one; the ledger of each step holds one `gate.finished` for each `gates.lint` and `gates.typecheck` command

## ADDED Requirements

### Requirement: L4-IMP-096 The static gates of a step come before its variant runs
A red step's static gates (check 6 of L4-IMP-002: every `gates.lint` and `gates.typecheck` command, judged against the
step base) SHALL run once per step, before the first run that the step's checks make with production code varied, swapped
or set aside: the zero-value run of the pre-satisfied confirmation, the base run (L4-IMP-003) and run (b). They SHALL so
run before a held check of the step is raised (L4-IMP-063) and before a recorded `accept` is applied to it. A step that
makes no such run SHALL run them where L4-IMP-002 lists them, after its red verdict. A static gate that passed at the step
base and fails SHALL fail the attempt at that point, with the text and feedback of check 6, and no later check of the
step SHALL run. The cheap checks that today come before the pre-satisfied confirmation (the criteria check, the per-test
cap of L4-VER-052) SHALL keep coming first. A red step that adds no test, changes no file and reports `already_satisfied`
SHALL make no static gate run, as today.

A green step whose test gate gives no failure SHALL run its static gates before the test-at-red run of corrected tests
(L4-IMP-063) and before an `at_red` accept is applied; a green step whose test gate failed SHALL NOT run them, as today.
The static gates of a red or green step SHALL run at most once per step. The repair chore (L4-IMP-091), the tests chore
and the fix chore SHALL keep their order.

#### Scenario: SCN-IMP-521 (−) A red step with a type error fails before the base run
- **Given** a red step in a project whose test gate is not pytest, whose new tests pass at head (so the zero-value run
  cannot decide them and they go to the base run), and whose `gates.typecheck` passed at the step base and fails now
- **When** the red checks run
- **Then** the attempt fails with the typecheck gate's text; no `test-base-run` gate runs, no `pre_satisfied` question
  is raised and nothing is captured for a replay

#### Scenario: SCN-IMP-522 (−) A replayed step with a lint error records no accept and makes no base run
- **Given** a held `pre_satisfied` check whose answer is `accept`, whose saved step, replayed, fails a `gates.lint`
  command that passed at the step base
- **When** the replay runs
- **Then** the attempt fails with the lint gate's text before the zero-value run and the base run; the replay itself is
  recorded (`held.replayed`), but the ledger holds no `check.accepted` and no `criterion.pre_satisfied` of the task

#### Scenario: SCN-IMP-523 (−) A red step with a lint error fails before run (b)
- **Given** a red step whose new tests fail by assertion against its stubs, and whose lint gate fails now
- **When** the red checks run
- **Then** the attempt fails with the lint gate's text and no zero-value gate of run (b) runs

#### Scenario: SCN-IMP-525 (−) A green step with a type error makes no test-at-red run
- **Given** a green step after a person unfroze a red test file, whose corrected tests pass at the green code, and
  whose typecheck fails now
- **When** the green checks run
- **Then** the attempt fails with the typecheck gate's text; no `test-at-red` gate runs and no `at_red` check is held or
  accepted
