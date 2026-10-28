# A test no run can vary is inconclusive, not rejected

## Why

A test chore whose task cites a criterion is checked as the verifier checks tests people or a chore wrote
(`discriminate_extra`, L4-VER-009, L4-VER-050): an added test counts when it fails by assertion with the project's
functions answering their zero value, or on the unit base's production code. Both runs vary Python files only:

- the zero-value run's scope is `imported_modules` (a test id is followed to its file by `_test_file`, which looks for
  `.py` files only) together with `_changed_modules` (`.py` files only);
- the base run swaps `production_changes` (`.py` files only).

In a project whose code is not Python both are empty, so neither run is made. Nothing is then accepted and nothing is
inconclusive, so every added test lands in `rejected`, and the chore fails with `none of the tests you added looks at
the answer: they pass when the project's functions answer their zero value and on the unit's base code`, though no
such run happened. The outcome does not depend on the test the agent writes [V, a consumer's TypeScript delivery plan]:

- a judge's finding that a test did not check the policy the design names became a fix unit's test chore citing the
  criterion (`C-…` in the task title);
- three attempts wrote that test in a new file (the first changed the frozen file in place and was put back); the
  ledger shows only the setup, test, lint and typecheck gates, and no `test-extra-zero` or `test-extra-base` run;
- the unit halted on `max_task_attempts (3) reached in single`. A chore does not escalate (`loop.py` returns early for
  the single phase), so no other profile was tried, and none could have passed.

L4-VER-050 already says a run that could not decide is no proof and is no rejection either, and that a test chore
whose tests are all inconclusive is held with a harness question. A check that could make no run at all is the same
case and gets the same answer.

## What Changes

- `discriminate_extra`: when there are tests to check, no module to vary (`imported_modules | _changed_modules` is
  empty) and no production file to swap (`production_changes` is empty), it makes no gate run and returns every test
  as rejected and inconclusive with `NO_RUN`: `neither run could be made: the zero-value run and the base run vary
  Python production files only, and the tests import no Python module of the project and the unit changed no Python
  production file`. `runs` is 0.
- `_discriminating_tests` (the test chore's check): unchanged, so a chore whose tests are all inconclusive is held
  with a harness question, no attempt used and nothing committed. The hold's `runs` names the two runs only when some
  run was made, so the question's `Runs:` line says `none` here.
- Step 4 (`_extra_proof_step`): unchanged; it takes only a test whose file is a Python file (`file_of_test`), so such
  a Python test's minor finding now says `inconclusive: neither run could be made: …` instead of `passes against the
  zero values and on the base`, and a TypeScript test is no candidate and keeps its `no proof` finding.
- `docs/SPEC.md`: L4-VER-050 names the case; a new scenario SCN-VER-242; change-table row 81. CHANGELOG 0.4.37 under
  Fixed.

## Impact

- Code: `l4.implementer.discrimination.discriminate_extra` (and its new `NO_RUN`),
  `l4.implementer.tdd._discriminating_tests`.
- Python projects: a test chore or a person's test in a unit that changed no Python production file, whose tests import
  no Python module of the project, was rejected and is now held (a chore) or an inconclusive minor finding (step 4).
  This follows L4-VER-050 (a check that ran nothing decides nothing). A hold is no pass: a person, or an agent where
  `clarifier.answer_by_agents` allows it, answers `accept` (the saved step is replayed under every guard and gate) or
  `retry`. Every other case, a Python unit that changed Python code included, makes the same runs as before.
- Security: no test is accepted without a run or an answer. The question shows the added tests' sources, so whoever
  answers reads what they check.
- Consumers: a unit halted this way goes on after an upgrade and `l4 retry --unit` (a retry starts a new attempt
  window, `deadline.RESETS`); its chore is then held with the question instead of failing.
- Out of scope, named in the design: a zero-value or base run for other languages (the module docstring's "M1:
  implementer-tdd-loop 2.2 for languages other than Python"), and chores never escalating to another profile.
