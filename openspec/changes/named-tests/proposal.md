## Why

A consumer's two delivery plans (21 units) stopped on the same kind of question again and again: the task or the
requirement said an EXISTING test had to change ("`test_all_tools_registered` gains the two tools", "the guard tests
are rewritten in place, none is deleted", "R5.5 names the functions"), and no step of the harness may change one.

- A red step that changes a test that existed before the step is rejected (L4-IMP-048, `preexisting_test_changes`,
  `src/l4/implementer/tdd.py:978`), unless the task is `[test-infra]` or the test is a stale test of a reopened task.
- A green step may not change a pre-existing test either (the test path freeze); only a person's answer that names the
  file opens it (L4-IMP-015).

So each such task ended in a question to a person, nine times in two plans, and the clarifier's suggested answers twice
proposed something the requirement forbids (deleting a test it says to keep, passing an argument positionally where a
default comes before it).

Two more stalls of the same plans had other causes:
- A support module the task line names (a test helper) that red created as a zero-value stub was frozen for green as "a
  red test of this task" (`named_by_task`, `src/l4/implementer/unfreeze.py:92`): green, whose job was to fill it in, was
  put back three times.
- Red attempts were rejected as vacuous five times in a row because their tests stopped with `NotImplementedError` from
  an earlier task's stub in another module: the zero-value run zeroes the stubs that HEAD holds only when red added no
  stub of its own (`tdd.py:1423-1425`), and the remedy text never said what the error was.

## What Changes

- **Red may change, in place, the existing tests that the reviewed text names** (L4-IMP-082). When the task's reviewed
  text, or the text of a criterion it cites, names a pre-existing Python test (`path::name`, or a test name that one
  test file defines), red is told so and may change that test's body. It may not delete it. The change is recorded as a
  `tests.superseded` event with `reason: named_by_task`, which the verifier already accepts and lists. Every other
  existing test stays protected.
- **A helper that red creates and the task line names stays open for green** (L4-IMP-083). A Python file red added,
  that the task's text names and that defines no test, is opened for that task's green, which may fill in its bodies
  but must keep red's names and signatures.
- **The zero-value run zeroes the stubs HEAD holds along with red's own** (L4-IMP-084).
- **The vacuity remedy names the error** (L4-IMP-085): a test that cannot import a module, or stops with
  `NotImplementedError` or `AttributeError` in the zero-value run, gets a remedy that names the module and says to stub
  it in this red step.
- **The clarifier reads signatures and keep-rules before it suggests an answer** (L4-CLR-007): two system rules, the
  signature lines of the functions the question calls in its excerpts, prompt version 6.

## Impact

- Code: `src/l4/implementer/` (`named_tests.py` new, `tdd.py`, `unfreeze.py`, `guards.py`, `opened.py`,
  `discrimination.py`, `prompt.py`, `templates/red.md`), `src/l4/clarifier/context.py`.
- Docs: `docs/SPEC.md` (requirements, scenarios, change row 64), `skills/` spec guidance, `CHANGELOG.md` (by the
  release).
- No config key, no ledger event type, no CLI change. The ledger gains a `reason` and `source` on `tests.superseded`;
  readers that ignore unknown fields are unaffected.
