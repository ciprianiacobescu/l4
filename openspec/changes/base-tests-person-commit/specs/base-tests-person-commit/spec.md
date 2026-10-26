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

### Requirement: Step 1 finds the file of a Go test
For a test id `<import path>::<name>` that the pytest rule gives no file, step 1 SHALL take as the test's file the one
`*_test.go` file directly in the package's directory that declares `func <name up to the first />(`, the directory
found from the `module` line of the `go.mod` whose module path is the longest prefix of the import path (equal to it,
or followed by `/`), looked up at head and then at the base. When no file or more than one declares it, the test SHALL
have no file, so it is a blocker unless `tests.superseded` names it.

#### Scenario: a Go module whose path is not its directory
- **WHEN** `apps/x/go.mod` says `module example.com/services/x`, a harness red commit and then a person's commit change
  `apps/x/internal/server/a_test.go`, which declares `func TestA(`, and `example.com/services/x/internal/server::TestA`
  fails with the base version of the file
- **THEN** it is a person's line that names both commits

#### Scenario: a subtest
- **WHEN** the failing id is `example.com/services/x/internal/server::TestA/case_one`
- **THEN** its file is the file that declares `func TestA(`

#### Scenario: no file declares the function
- **WHEN** no `*_test.go` file of the package's directory declares the function of a failing Go id
- **THEN** it is a blocker
