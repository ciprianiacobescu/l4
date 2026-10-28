## Purpose

A test that people or a test chore wrote, which neither the zero-value run nor the base run can vary, is inconclusive
with that reason, so a test chore in a project whose code is not Python is held for an answer instead of failing every
attempt.

## ADDED Requirements

### Requirement: L4-VER-050 A test no run can vary is inconclusive
When tests that people or a test chore wrote are checked (`discriminate_extra`, L4-VER-009), and the tests import no
Python module of the project, the unit changed no Python production file, and so neither the zero-value run nor the
base run has anything to vary, the check SHALL make no gate run and SHALL return every test as inconclusive with the
reason `neither run could be made: the zero-value run and the base run vary Python production files only, and the tests
import no Python module of the project and the unit changed no Python production file`. Such a test SHALL NOT be
rejected as one that passes against the zero values and on the base. A test chore whose added tests are all
inconclusive this way SHALL be held with a harness question (L4-IMP-063, `check: tests`) whose `Runs:` line is
`none`, with no attempt used and nothing committed; step 4 SHALL give such a test the minor finding
`inconclusive: <reason>`. When either run has something to vary, the check SHALL make the runs it made before.

#### Scenario: SCN-VER-242 (−) a TypeScript test chore is held, not failed
- **WHEN** a fix unit's test chore that cites a criterion adds `src/pricing/total.test.ts` in a project whose tests
  import no Python module and whose unit changed no Python production file
- **THEN** no gate runs, the task is held with a harness question whose reason starts `neither run could be made` and
  whose `Runs:` line is `none`, no attempt is used, and nothing is committed

#### Scenario: step 4 says why a test no run can vary has no proof
- **WHEN** step 4 decides the proof of a test a person wrote, carrying a criterion, that no run can vary
- **THEN** it is no evidence, and its minor finding is `inconclusive: neither run could be made: …`, not that it
  passes against the zero values and on the base

#### Scenario: a Python unit that changed Python code makes its runs as before
- **WHEN** a test chore adds tests that pass with the project's functions answering their zero value and on the base,
  in a unit that changed Python production code
- **THEN** both runs are made and the attempt fails with `none of the tests you added looks at the answer`, as before
