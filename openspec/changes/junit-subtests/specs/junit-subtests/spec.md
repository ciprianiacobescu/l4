## ADDED Requirements

### Requirement: L4-GAT-006 A subtest is read as part of its test
A testcase whose classname is a dotted Python name and whose name is a `test…` method name followed by a unittest
subtest description SHALL be read into `classname::<method>`, with the worse result of the test and its subtests, the
first of two equal ones, all criteria and a message that starts with the subtest's description. Other names SHALL be
read as before.

#### Scenario: SCN-GAT-08 (+) Failing subtests are one failing test
- **WHEN** a report holds two failing subtest testcases of `test_rejects_bad_values_C-1a2b3c4d`
- **THEN** it holds one failed test with that id, kind `assertion`, whose message names the first subtest

#### Scenario: SCN-GAT-09 (+) A red test with subtests passes green
- **WHEN** green's report holds only the passing method testcase
- **THEN** no red test is still failing

#### Scenario: SCN-GAT-10 (−) Other names stay as they are
- **WHEN** a report holds a pytest parameter id, a JavaScript title and a Java display name with brackets
- **THEN** each keeps its own id
