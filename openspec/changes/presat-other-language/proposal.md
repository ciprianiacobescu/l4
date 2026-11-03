## Why

A consumer's TypeScript unit halted on a task whose behaviour an earlier task of the same unit had already built. Task
2.2's green implemented what task 2.3 asks for, so 2.3's new tests passed at head and the red step went to the
pre-satisfied confirmation. All three red attempts failed with `not discriminating: C-… (no project source module is
imported by those tests; none of its new tests fails by assertion against the unit base code)`, and the unit halted on
`max_task_attempts`. A retry or a reworded test cannot help.

The zero-value run of `confirm_pre_satisfied` varies Python files only: its scope (`imported_modules`,
`_changed_modules`) holds `.py` files only. In a TypeScript project that scope is always empty, and the empty-scope exit
refutes the criterion without running anything. That contradicts L4-IMP-060: a criterion is not discriminating only
when every one of its tests ran and none is a proof. The base run, which is language-neutral, only confirms
(`combine`): it errored at the unit base here (a test support file calls a function that was a stub there), so the
refutation stood.

The verifier's check of tests that people or a test chore wrote already treats this case (L4-VER-050, change 82
`test-file-reach`): a test in a file of another language that no run accepted is inconclusive, not rejected. The
pre-satisfied confirmation never got the same rule.

## What Changes

- In the pre-satisfied confirmation, a new test whose file `file_of_id` finds among the work tree's files with the
  extension of another language (`OTHER_LANGUAGES`), and that the zero-value run did not reach (it did not fail there,
  by assertion or by an error), is inconclusive with `the zero-value run varies Python files only, and <file> is not a
  Python file`. It is not counted as having run, at the empty-scope exit and in the zero-value run's judgement alike.
- A criterion is then decided by L4-IMP-060: confirmed when any of its tests is a proof, inconclusive when none is and
  any is inconclusive, not discriminating only when every one of its tests ran and none is a proof.
- An inconclusive criterion goes to the base run as today. When the base run does not confirm it, the task is held with
  a `pre_satisfied` harness question (L4-IMP-063). It is never passed: only an `accept` lets it count, and `retry`
  gives the implementer another attempt.
- Python tests, and tests whose file is not found, keep today's rules, the empty-scope refutation included.

## Impact

- Code: `l4.implementer.discrimination.confirm_pre_satisfied` and a constant for the reason.
- Spec: L4-IMP-092 (new); a sentence in the "Confirmation by a base run" paragraph; SCN-IMP-485..488; change-table row
  117.
- Behaviour: in a project whose tests are not Python, a red step whose new tests pass at head and that no earlier red
  and no base run confirms is held for a person, or for the delegate where the base branch allows it, in place of
  failing its attempts until the unit halts. A vacuous test that passes at head is therefore held, not sent back to the
  agent at once; the holder's `retry` answer sends it back.
- Not changed: the base run, `combine`, `_decide_pre_satisfied`, the hold's question and its answers.
