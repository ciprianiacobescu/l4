## Why

A red step must give every criterion it cites a NEW test that traces it (`check_criteria`, L4-IMP-005). Two kinds of
task cannot meet that rule honestly.

**A task that names an existing test to change in place.** A consumer's TypeScript unit had a task whose reviewed text
names `registry.test.ts::C-… the registry lists …`, an existing test that carries the criterion's id in its name. Red
changed that test as the task says, so it failed by assertion against the current code, and wrote no other test for
that criterion. Every attempt failed with `no new test traces C-…`: a test changed in place keeps its id, so
`new_test_ids` never holds it. The unit used 7 attempts over all 3 implementer profiles, then halted. A consumer's
Python unit failed the same way twice. When red writes no new test at all, the step fails in `classify_red` instead
(`no new test: the test the task names does not count as a new test: …`). Consumers work around it with a rule in
their agent notes: add a new test, named with the id, beside the edited one. That copy proves nothing the edited test
does not.

**A fresh task that cites a criterion the unit does not change.** An OpenSpec delta that MODIFIES a requirement restates
its scenarios; a scenario restated word for word keeps the id and the text of the archived one, and the tests on the
base that trace it pass. A task that cites it still needs a new test. A new test of behaviour the base already has
passes at red, so the step goes to the pre-satisfied confirmation, where the base run cannot confirm it (the test
passes at the unit base too) and, in a project that is not Python, the zero-value run cannot reach it (L4-IMP-092): the
task is held for a person or the delegate. The verifier already accepts such a criterion pass-to-pass (L4-VER-009); red
asks for a test the verifier does not need, and the test it asks for guarantees the hold. Only a task that a spec edit
reopened is exempt today (L4-OPS-015).

The retry hint of `no new test traces` also shows `it("C-xxxxxxxx: …")` in a Python project whose test gate does not
run pytest (a Django test runner): `trace_rules` knows only "pytest" and "anything else".

## What Changes

- A test the task's reviewed text names (L4-IMP-082, L4-IMP-089) traces a cited criterion like a new test when red
  changed it in place, it passed in the step's base report, it fails at red by assertion (not by an error, the stub's
  `NotImplementedError` or a hang), its trace holds the criterion, and it traces at most `verifier.max_criteria_per_test`
  of the unit's criteria. It then counts for that criterion's tracing tests and proof; it is still not a new test, and
  the task still never ends as already satisfied. A red step whose only tests are such named tests is checked like any
  red step.
- A named test that traces a cited criterion and does not count keeps today's reason, followed by a note that names it
  and says why it does not count.
- A criterion is *unchanged on the base* when the verifier's pass-to-pass rule holds for it at the unit base (the same
  id and the same normalised text in the archived specs, read from git) and a test of the step's base report traces it,
  passed there, passes at red and traces at most `verifier.max_criteria_per_test` of the unit's criteria. Any task, fresh
  or reopened, needs no new test for such a criterion; a passing new test of it is confirmed by the base specs without a
  run (`via: "unchanged_spec"`), so it is not held; a task whose every cited criterion is unchanged on the base ends as
  already satisfied without a zero-value or base run.
- Red and the verifier read "unchanged" through one helper, so red never asks for a test that the verifier would have
  accepted pass-to-pass.
- A test gate that runs Python tests without pytest (its command names `python`, `manage.py`, `unittest`, `nose2` or
  `xmlrunner`) is told the Python name form, `def test_c_xxxxxxxx_…`, in the contract and in the retry hint.
- The red prompt's `# Existing tests this task changes in place` section says that a listed test that traces a cited
  criterion and fails by assertion after the change counts for it.

## Impact

- Code: `l4.implementer.result` (`check_criteria`, the trace rules, `tag_example`); `l4.implementer.tdd` (`run_red`,
  `classify_red`, two new helpers, `_via`); `l4.implementer.prompt._named_section`; `l4.specs.criteria` (two helpers
  the verifier also uses); `l4.verifier.traceability._unchanged` and `l4.verifier.ladder` (call the helpers; no change
  of behaviour).
- Spec: L4-IMP-093 (new); amendments of L4-IMP-082, L4-IMP-089, L4-KSP-012, L4-IMP-003 and the §7.4 paragraph on the
  trace form; SCN-IMP-440 amended; SCN-IMP-490..499; change-table row 118.
- Behaviour: a task that names a test to change in place no longer needs a copy of it; a task that cites an unchanged,
  already tested scenario is neither asked for a test nor held; a Python project whose gate is not pytest gets a Python
  example. Templates: none (`red.md` stays at version 13).
- Not changed: the pre-satisfied confirmation of every other criterion, `combine` and the hold; L4-OPS-015's own
  exemption; the verifier's pass-to-pass rule; green.
