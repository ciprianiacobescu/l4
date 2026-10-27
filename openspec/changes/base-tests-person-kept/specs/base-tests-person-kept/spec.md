## Purpose

A test or support file whose last change in `base..head` is a person's commit runs at head in step 1's run of the base
tests, so a person's commit that L4-IMP-081 asks for also holds for the tests that run that file.

## ADDED Requirements

### Requirement: A file a person changed last stays at head for the run
In step 1 (L4-VER-038), a test or support file the unit changed SHALL stay at head for the run of the base tests when
the last commit of `base..head` that changed it is not the harness's (the author rule, `is_harness`), after the
existing reasons (only people's commits, a `[test-infra]` task, a `task.unfrozen`). It SHALL be listed as a person's
line, `<path> kept at head for the run (people changed it last (<sha>, …))`, naming every commit of `base..head` that
changed it, the harness's included. When a harness commit changed it after the person's last commit, it SHALL be put
back to its base version, as before.

#### Scenario: a harness red step, then a person
- **WHEN** a harness commit (red) changes `pkg/a_test.go` and a later person's commit changes it again
- **THEN** `pkg/a_test.go` stays at head for the run and is a person's line that names both commits

#### Scenario: the harness after the person
- **WHEN** a person's commit changes `pkg/a_test.go` and a later harness commit (green) changes it again
- **THEN** `pkg/a_test.go` is put back to its base version for the run

#### Scenario: a test the unit did not change runs the kept file
- **WHEN** `pkg/a_test.go` stays at head because a person changed it last, and `tests/test_meta.py`, which the unit did
  not change, runs the package's tests and passes with the head version of `pkg/a_test.go`
- **THEN** step 1 has no blocker
