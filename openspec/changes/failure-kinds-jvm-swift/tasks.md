## 1. JVM and Swift failure kinds

- [x] 1.1 Fixtures: copy the recorded reports into `tests/fixtures/recorded/surefire/` (`TEST-x.kinds.Jupiter5Test.xml`,
  `TEST-x.kinds.Junit4StyleTest.xml`, `TEST-x.kinds.TruthTest.xml`) and `tests/fixtures/recorded/swift/`
  (`xunit.xml`, `xunit-swift-testing.xml`), with a `VERSIONS` file (Surefire 3.5.2, JUnit Jupiter 5.11.4, Vintage
  5.11.4, JUnit 4.13.2, Truth 1.4.4, Swift 6.4 `swift test --parallel --xunit-output`). Take out Surefire's
  `<properties>` and any `system-out`/`system-err`, absolute path or user name; keep every `<testcase>` and its
  `<failure>`/`<error>` exactly. Grep the result for `/Users/`, `/home/`, the machine's user name and host name: none.
  Result: the three Surefire reports lost only their `<properties>` block (the rest held no system-out/err or path); the
  two Swift reports are unchanged; each folder has a `VERSIONS`; the grep prints nothing.
- [ ] 1.2 Tests first in `tests/unit/gates/test_junit_recorded.py` (each recorded failure → its kind: JUnit 5 four
  assertions, NPE other, `UnsupportedOperationException` not_implemented; JUnit 4 both assertions; Truth both
  assertions; Swift Testing two assertions and one other; SwiftPM XCTest `message="failure"` stays None) and
  `tests/unit/gates/test_junit.py` (the Truth rule's limits: `type="expected"` with a message that does not start with
  `expected:` is not an assertion; a dotted or capitalised type is not read by it). Then `junit._type_kind` and
  `_message_kind` as the design says. Run `tests/unit/gates`, `tests/unit/implementer/test_tdd_red.py`,
  `tests/unit/implementer/test_red_evidence.py`, `tests/unit/implementer/test_variant.py`.

## 2. Docs (one pass at the end of the release)

- [ ] 2.1 docs/SPEC.md L4-IMP-002 red-check paragraph names the new kinds; SCN-IMP-415 to SCN-IMP-417; change-table row 84;
  CHANGELOG 0.4.38; docs/runbook.md known limits: XCTest through `swift test --xunit-output` gives no failure kind.
