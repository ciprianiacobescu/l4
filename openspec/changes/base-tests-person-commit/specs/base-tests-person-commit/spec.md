## Purpose

The way out that L4-IMP-081 names for a test file a fix chore may not change, a person's commit on the unit branch,
works in step 1 of the verifier even when a harness step changed the file before.

## ADDED Requirements

### Requirement: A person's last commit to a test file excuses its failing base tests
In step 1 (L4-VER-038), a test that passed at the base and fails, no longer runs or no longer collects with the base
version of its file SHALL be a person's line, not a blocker, when the last commit of `base..head` that changed its
file is not the harness's (the author rule, `is_harness`). The line SHALL name every commit of `base..head` that
changed the file, the harness's included. When a harness commit changed the file after the person's last commit, the
test SHALL stay a blocker unless another allowance covers it.

#### Scenario: a harness red step changed the test, then a person set the file
- **WHEN** a harness commit (red) changes `tests/test_a.py` and a later person's commit changes it again, and
  `tests.test_a::test_a` fails with the base version of the file
- **THEN** it is a person's line that names both commits, and no blocker

#### Scenario: the harness changed the file after the person
- **WHEN** a person's commit changes `tests/test_a.py` and a later harness commit (green) changes it again, and
  `tests.test_a::test_a` fails with the base version of the file
- **THEN** it is a blocker

#### Scenario: only people changed the file
- **WHEN** only a person's commit changes `tests/test_d.py` and `tests.test_d::test_d` fails with its base version
- **THEN** it is a person's line, as before
