# Design: failure kinds of JVM and Swift reports

## D1. Recorded, not invented

The shapes come from real runs on 2026-10-28 (versions in the proposal). The fixtures are those reports with only the
machine-specific parts taken out (Surefire's `<properties>`, `system-out`, `system-err`, absolute paths); every
`<testcase>` and its `<failure>`/`<error>` stays byte for byte. A shape from another reporter (Gradle's XML, xcbeautify,
fastlane's trainer) is not claimed: it is read by the same rules, unverified.

## D2. Truth's facts

Truth's `AssertionErrorWithFacts` prints its message without its class name, so Surefire's `type` is the message's
start (`expected`, `expected to contain`). The rule is narrow: the `type` equals the text before the first `:` of the
message's first line, has no `.`, and starts with a lower-case letter. A Java exception's type is a class name (a
package with dots, or a capital letter), so no other report meets all three. Truth's error is an `AssertionError`, so
the kind is assertion.

## D3. `UnsupportedOperationException` is the stub's error

Red's prompt names `throw UnsupportedOperationException()` as the Java/Kotlin stub form (L4-IMP-002), so its failure must count
as the stub's error, with any message (the stub has none). Code that throws it for a real unsupported operation is read
the same way, as `NotImplementedError` is for Python.

## D4. Swift Testing by message, XCTest left without a kind

Swift Testing writes no `type`; its message says what happened (`Expectation failed:` for `#expect`/`#require`,
`Caught error:` for a thrown error). XCTest through SwiftPM gives `message="failure"` for both cases, so no rule can be
right; it keeps no kind, and the runbook's known limits say so (use a reporter that writes the assertion message).

## D5. Order

The message still wins: the new message rules sit with the existing ones; the type rules apply only when the message
gave no kind.
