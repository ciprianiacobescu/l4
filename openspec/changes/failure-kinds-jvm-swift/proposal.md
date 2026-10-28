# The red check reads the failures of JUnit 5, JUnit 4, Truth and Swift Testing

## Why

Red's failure check classes a failing new test by its report: the message first, then the `type` attribute of the
`<failure>` (`junit._message_kind`, `junit._type_kind`). A new test must fail by assertion, or with the stub's
not-implemented error. Reports recorded on 2026-10-28 (Maven Surefire 3.5.2 with JUnit Jupiter 5.11.4, the JUnit
Vintage engine with JUnit 4.13.2, Truth 1.4.4; Swift 6.4 `swift test --parallel --xunit-output`) show that these are
read wrong today:

| Framework | `<failure>` | Kind today | Kind meant |
|---|---|---|---|
| JUnit 5 (`assertEquals`, `assertTrue`, `assertThrows`, `fail`) | `type="org.opentest4j.AssertionFailedError"` `message="expected: <2> but was: <3>"` | other | assertion |
| JUnit 4 `assertEquals` of strings | `type="org.junit.ComparisonFailure"` | other | assertion |
| Truth `assertThat(…).isEqualTo(…)` | `type="expected"` `message="expected: 2⏎but was : 3"` (Truth's error prints no class name, so Surefire takes the message's start as the type) | none | assertion |
| Java/Kotlin stub `throw UnsupportedOperationException()` (the stub form red's prompt names) | `type="java.lang.UnsupportedOperationException"` | other | not implemented |
| Swift Testing `#expect`, `#require` | `message="Expectation failed: 1 + 2 == 2 (error)"`, no type | none | assertion |
| Swift Testing, an error thrown | `message="Caught error: MyError() (error)"` | none | other |

So a red step in a JUnit 5 or Swift Testing project can never pass: every new test is "vacuous". Kotlin's
`kotlin.test` on JUnit 5 and Kotest throw the same `AssertionFailedError`; Kotlin's `TODO()` (`NotImplementedError`) is
read right today.

XCTest through `swift test --parallel --xunit-output` writes `<failure message="failure">` for every failure, with no
type and no text, whether an assertion failed or an error was thrown: the report cannot tell them apart, and it stays
without a kind.

## What changes

- `_type_kind`: a last name that ends with `AssertionFailedError`, or is `ComparisonFailure`, is an assertion;
  `UnsupportedOperationException` is the stub's not-implemented error.
- `_type_kind`: a `type` that is the start of the message itself (the text before the first line's `:`), with no dot
  and starting with a lower-case letter, is an assertion (Truth's facts).
- `_message_kind`: a first line that starts with `Expectation failed:` is an assertion; `Caught error:` is another
  error.
- The recorded reports go to `tests/fixtures/recorded/surefire/` and `tests/fixtures/recorded/swift/` with their tool
  versions, the Surefire `<properties>` and the machine-specific output taken out.

## Impact

- Code: `l4.gates.junit`.
- Behaviour: red steps of JUnit 5, JUnit 4, Truth and Swift Testing projects can pass; the classes of pytest, Vitest
  and .NET reports do not change.
- Docs: the red-check paragraph of L4-IMP-002 (docs/SPEC.md, the list of failure kinds), scenarios SCN-IMP-415 to
  SCN-IMP-417, change-table row 84, CHANGELOG 0.4.38, and a known limit for XCTest through SwiftPM.
