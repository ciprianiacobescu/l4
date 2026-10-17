Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Implementer (L4-IMP-003)

- [x] 1.1 Tests: `tests/unit/implementer/test_earlier_red.py` (SCN-IMP-206), `test_already_satisfied.py` (SCN-IMP-207,
  SCN-IMP-208, SCN-IMP-209, SCN-IMP-210).
- [x] 1.2 `earlier_red._test_file` walks dotted prefixes at the red sha; `run_red` takes the no-test path; `red.md` and
  `NO_NEW_TEST` say when to add no test and that `already_satisfied` needs the task's own text to be true.

## 2. Verifier (L4-VER-018)

- [x] 2.1 Tests: `tests/unit/verifier/test_judge_satisfied.py` (SCN-VER-72..75).
- [x] 2.2 `SatisfiedRef`, the satisfied block and rule in `judge.py` (`PROMPT_VERSION` 9), `satisfied` in the reply
  model and `judge-verdict.schema.json`, `satisfied_ids` in `_unanswered`/`_ask_missing`, the findings and
  `verify.satisfied_judged` in `ladder._judge_step`.

## 3. Step secrets (L4-SEC-008)

- [x] 3.1 Tests: `tests/unit/vcs/test_secretscan.py` (SCN-SEC-20, SCN-SEC-21 for `worktree_secrets`), an agent-step
  test that a fixture token fails the attempt with no gate run and no `breaker.tripped`.
- [x] 3.2 `secretscan.worktree_secrets`, the check in `tdd.agent_step`, the contract template rule.

## 4. Docs

- [x] 4.1 `docs/SPEC.md` (L4-IMP-003, L4-VER-018, L4-SEC-008, the scenarios, the change row), `docs/runbook.md`, the skill's
  `spec.md` (the tasks rule), `CHANGELOG.md` (`## 0.4.8 (unreleased)`).
- [x] 4.2 `openspec validate check-already-satisfied --strict`.
