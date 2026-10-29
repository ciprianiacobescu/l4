# Design: junit-subtests

- `_SUBTEST = (?P<method>test[^\s\[\]()]*) (?P<desc>(?:\[.*?\] )?\(.*\)|\[.*\])`, full match, only with a classname that
  is a dotted Python name: unittest's `_SubTest.id()` is the test id, a space and `[msg] (params)`; the `test` prefix
  and the bracket-free method keep pytest parameter ids (`test_x[a (1)]`) and Java or JavaScript display names
  (`sum (positive)`, `renders the list (empty)`) out.
- `_fold(held, read)`: the worse status by `_WORSE` (the order of L4-GAT-005), on equal failures the worse kind
  (`other`/unknown, `not_implemented`, `assertion`; review: the first of two equal ones let a `NotImplementedError`
  subtest hide a `TypeError` one from red's kind check), then the earlier case; the union of criteria; and
  `assertion_failed` when any folded case failed by assertion. An erroring subtest beats a failing one, so red's kind
  check sees the error, while the zero-value and base runs (`variant.test_outcome`) take `assertion_failed` as a proof:
  a test one of whose subtests fails by assertion under the zero values discriminates.
- Names longer than 2000 characters are not matched (the pattern backtracks on brackets); a subtest's description is
  cut at 120 characters in a message; module and class names may be any Python identifiers.
- Recorded fixtures: `tests/fixtures/recorded/xmlrunner/subtests-{red,green}.xml`, written by unittest-xml-reporting
  4.0.0 on Python 3.10 (paths in the tracebacks replaced by `/work/tests/`).
