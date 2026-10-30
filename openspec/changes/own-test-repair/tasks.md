## Context

Builds on fix-chore-e2e (the round's `failures` map; one task per failure; the e2e gate in a fix chore). Pointers
(verified on v0.4.44, re-locate): `run_single` (src/l4/implementer/tdd.py ~2310; kinds fix/tests/refactor),
`review_test_chore` (~2177) and `_appended`, `l4.implementer.tamper.facts_of` (AST facts per bound name: definition and
closure digests), `l4.specs.fixmark` (`test_chores`, `refactors`, `chore_kind`), `l4.verifier.fixunit._candidates`,
`l4.verifier.integrity._allowed_in_step` and `check_test_paths` (~600-640; walks commits with `L4-TDD` green, exempt,
already-done), the red-freeze check (find it: red's frozen tests unchanged after red), `unit_base` (discrimination.py
~720-730), `judge.NamedChange` and `ladder._named_changes` (0.4.43), the template lock (`uv run python -m
l4.templatelock --write`), `l4.implementer.prompt` templates.

## 1. Candidates and the marker

- [ ] 1.1 Write the tests first (the fixunit and fixmark tests): SCN-IMP-455, SCN-IMP-456 (TypeScript; a mixed finding),
  a person's test (first added by a commit without `L4-TDD: red`), a support-glob file (`conftest.py`), and a candidate
  finding → `repair` chore. Verify (and pin with a test) that `unit_base(wb)` inside a fix unit is the parent's base.
  Then add `repairs` to the fix marker (a list of finding ids, absent = none, old markers read as before), `chore_kind`
  `repair` when every finding of the task is in `repairs`, and the candidate rule in `fixunit` (L4-IMP-091 first
  paragraph). The task text names each test, its kind and first line, carries the finding's gate log excerpt (bounded,
  redacted), and says the test may be right and the code wrong.

## 2. The structural check

- [ ] 2.1 Write the tests first (a new `tests/unit/implementer/test_repair_check.py`, pure: text before/after → findings):
  every bullet of L4-IMP-091's second paragraph, both ways (SCN-IMP-451, -452, -457, the two consumer repairs:
  `expect(page).to_have_url(lambda …)` → `page.wait_for_url(lambda …)` and adding `exact=True` to a `get_by_role` call
  are kept). Then add a pure module (next to `l4.implementer.tamper`, no public name starting with `test`) that returns
  the rule each change breaks, or nothing.

## 3. The repair step and the verifier

- [ ] 3.1 Write the tests first (the run_single tests): SCN-IMP-450, -453, -454, -458. Then add `run_single(kind="repair")`
  with its own prompt template `single_repair` (the tests, kinds, first lines, log excerpt, the rules of the check, "the
  test may be right and the code wrong: if so, report blocked with a technical question"), put back and fail on any
  change outside the candidates' files, run the structural check, then the gate the tests failed in (fix-chore-e2e's e2e
  path, or the test gate with them as must-pass), commit with `L4-TDD: exempt` and record `task.repaired{task, files,
  tests}`. Regenerate the template lock.
- [ ] 3.2 Write the tests first (the integrity tests and the judge prompt tests): SCN-VER-257, SCN-VER-258, and that a
  plain exempt commit changing the same file is still a blocker. Then accept `task.repaired` files in `_allowed_in_step`
  for exempt commits of the same unit and task, the same in the red-freeze check, and give the judge each repaired test's
  lines before and after (reuse `NamedChange`).

## 4. Checks

- [ ] 4.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the test files that import a module you changed, in as few sequential runs as the time limit
  allows; not whole directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit
  docs/SPEC.md, CHANGELOG.md or docs/runbook.md.
