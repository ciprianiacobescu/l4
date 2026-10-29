# A subtest is read as part of its test

## Why

unittest-xml-reporting writes a testcase for each failing subtest (`<method> (params)`) and, when every subtest of a
test passes, one testcase for the method. A red step whose new test used `self.subTest` recorded each failing subtest
as a new test id; after a green step that made the whole suite pass, those ids were not in the report, so `green_failures`
said `red tests still failing` on every attempt and every profile, and the unit halted [V: a consumer's unit on
2026-10-29: three green attempts, each gate run `Ran 667 tests … OK`, each rejected].

## What changes

- `parse_junit` reads a testcase whose classname is a dotted Python name and whose name is a `test…` method followed by
  a subtest description into `classname::<method>`, keeping the worse result (error, failed, passed, skipped) of the
  test and its subtests, the first of two equal ones, all criteria, and a message prefixed with the subtest's
  description. The failure kind is read from the subtest's own message.
- Other names keep their ids; a duplicate id that is no subtest keeps the last entry, as before.
- `fold_subtest_id` maps a stored subtest id (a ledger written before this rule) to its test's id wherever ledger ids are
  compared with a report: green, a resumed red, the verifier's expected tests, traceability, the earlier-red check and
  integrity.

## Impact

- Code: `l4.gates.junit`. Every reader of a report (red, green, the zero-value and base runs, the verifier) sees the
  test's id instead of its subtests' ids.
- Spec: L4-GAT-006; SCN-GAT-08 to SCN-GAT-10; change-table row 91.
