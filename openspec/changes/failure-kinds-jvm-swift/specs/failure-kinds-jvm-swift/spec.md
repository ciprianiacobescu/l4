## Purpose

Red's failure check reads the assertion failures of JUnit 5, JUnit 4, Truth and Swift Testing reports as assertions, and
the Java/Kotlin stub's error as the stub's.

## ADDED Requirements

### Requirement: L4-IMP-002 Red reads JVM and Swift failure kinds
Red's failure check SHALL class as an assertion: a `<failure>` whose `type`'s last name ends with
`AssertionFailedError` or is `ComparisonFailure`; a `type` that is the text before the first `:` of the message's first
line, with no `.` and starting with a lower-case letter; and a message whose first line starts with `Expectation
failed:`. It SHALL class a `type` whose last name is `UnsupportedOperationException` as the stub's not-implemented
error, and a message whose first line starts with `Caught error:` as another error. The message SHALL still be read
before the type.

#### Scenario: SCN-IMP-415 (+) JUnit 5, JUnit 4 and Truth failures are assertions
- **WHEN** a red step's new tests fail in a Surefire report with `type="org.opentest4j.AssertionFailedError"`,
  `type="org.junit.ComparisonFailure"`, and `type="expected"` with `message="expected: 2⏎but was : 3"`
- **THEN** each is an assertion failure, and the red step accepts them

#### Scenario: SCN-IMP-416 (+) the Java stub's error is not implemented
- **WHEN** a new test fails with `type="java.lang.UnsupportedOperationException"` from a stub
- **THEN** it fails with the stub's not-implemented error, as `NotImplementedError` does in Python

#### Scenario: SCN-IMP-417 (+/−) Swift Testing failures by message
- **WHEN** a Swift Testing report has `message="Expectation failed: 1 + 2 == 2 (error)"` and `message="Caught error:
  MyError() (error)"`, with no type
- **THEN** the first is an assertion and the second another error
