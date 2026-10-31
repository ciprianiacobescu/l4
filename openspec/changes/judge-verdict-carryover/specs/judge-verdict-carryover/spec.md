## ADDED Requirements

### Requirement: L4-VER-072 A round whose judge gave no verdict keeps the earlier judge's pass of an unchanged criterion
When step 9 of a fresh round ran and ended with no judge verdict, the harness SHALL give a criterion the `pass` of the newest
earlier round that has a judge verdict only when the criterion's source file is the same at both heads, every path that
changed between the two heads is in a directory of the unit family or is a test file that matches no support glob, none
of those test files holds a test that traces the criterion at either round, no test traces it now that did not then, and
every test that traces it passes now. The earlier round's test-adequacy entries for the criterion SHALL be applied with
it, its reason SHALL say that it was carried and from which round and head, and `verify.carried` SHALL record it. The
carried verdict and its adequacy entries SHALL be stored with the round (`judge_carried`) so that a resumed round keeps
them without reading the earlier round. The round SHALL keep the hold of the discarded reply and SHALL NOT carry
findings. A failure to read the earlier round or the
diff SHALL carry nothing and SHALL be recorded as `verify.not_carried`.

#### Scenario: SCN-VER-273 (+) a round whose judge timed out after a test-only change asks only about the new test's criteria
- **WHEN** round 1 passed criteria A, B and C at head H1, the head H3 adds only a test file whose tests trace C, and round
  3's judge times out
- **THEN** A and B pass with `the judge of round 1 passed it at <H1>, and only tests that do not trace it changed since
  (carried)`, `verify.carried` names A and B, C is asked, and the round holds `the judge's reply was discarded …`

#### Scenario: SCN-VER-274 (−) a production change carries nothing
- **WHEN** a code file changed between the two heads
- **THEN** no criterion is carried, `verify.not_carried{reason: "a non-test file changed", paths}` is recorded, and every
  criterion is asked as before

#### Scenario: SCN-VER-275 (−) a changed criterion, a changed tracing test or a new tracing test is not carried
- **WHEN** a criterion's source file changed, or the file of a test that traces it changed, or a new test traces it
- **THEN** that criterion is asked, and the others are carried when they qualify

#### Scenario: SCN-VER-276 (−) only a pass is carried, and a human verdict or a failing test still decides
- **WHEN** the earlier verdict of a criterion is not `pass`, or a person's verdict is in force, or a tracing test fails
  now
- **THEN** the criterion is not carried as a pass: it is asked, takes the person's verdict, or fails, as without carry-over

#### Scenario: SCN-VER-277 (−) a round whose judge answered or whose step 9 did not run carries nothing, and a resumed round keeps its carried passes
- **WHEN** the round's judge answered, or its step 9 did not run, or the round of SCN-VER-273 is resumed after a person
  accepts the hold and C
- **THEN** no verdict is carried in the first two cases; the resumed round passes A and B with the carried reason and C
  and the hold with the person's verdicts, with no judge call and no read of round 1
