# Design: junit-subtests

- `_SUBTEST = (?P<method>test[^\s\[\]()]*) (?P<desc>(?:\[.*?\] )?\(.*\)|\[.*\])`, full match, only with a classname that
  is a dotted Python name: unittest's `_SubTest.id()` is the test id, a space and `[msg] (params)`; the `test` prefix
  and the bracket-free method keep pytest parameter ids (`test_x[a (1)]`) and Java or JavaScript display names
  (`sum (positive)`, `renders the list (empty)`) out.
- `_fold(held, read)`: the worse status by `_WORSE` (the order of L4-GAT-005), the earlier case on a tie, the union of
  criteria. An erroring subtest beats a failing one, so a red test whose subtest errors against a stub is not taken as
  failing by assertion.
- Recorded fixtures: `tests/fixtures/recorded/xmlrunner/subtests-{red,green}.xml`, written by unittest-xml-reporting
  4.0.0 on Python 3.10 (paths in the tracebacks replaced by `/work/tests/`).
