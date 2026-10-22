Every task follows these rules:
- Read `proposal.md`, `design.md` and `specs/named-tests/spec.md` of this change first. Every text, field, signature
  and version is in `design.md` (D1 to D6 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree, with its own `.venv` (`uv sync --inexact`). Never change git configuration.
  Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `named-tests <n.m>: …`, with no
  trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- Name a consumer repository only as "a consumer". Put no local path in docs or fixtures, and no test name or path
  taken from a consumer's repository beyond the generic ones of the scenarios.
- One implementer does the tasks in order, on top of the previous commits.

Test worlds: `tests/unit/implementer/conftest.py` (`make_bench`, `Bench`, `red_step`, `result`, `KNOWN`, `STUB`);
`tests/unit/implementer/test_red_preexisting_tests.py` (L4-IMP-048, the model for D2);
`tests/unit/implementer/test_named_unfreeze.py` (named_by_task); `tests/unit/implementer/test_opened.py`;
`tests/unit/implementer/test_vacuity.py`; `tests/unit/implementer/test_tdd_red.py`;
`tests/unit/implementer/test_prompt.py`; `tests/unit/verifier/` (integrity listing);
`tests/unit/clarifier/test_context.py`.

## 1. Named existing tests (D1, D2; L4-IMP-082)

- [x] 1.1 `src/l4/implementer/named_tests.py`: `MAX_NAMED_TESTS`, `NamedTests` (with `ids()`), `find_named` (pure) and
  `named_tests(wb, task, base)` as D1 says. Tests (new `tests/unit/implementer/test_named_tests.py`): node id with and
  without class and `[param]`; a bare name in one file; a bare name in two files (kept text); a token that is no test;
  the cap of 5 (kept text); criterion texts counted for a `plan:` source and for an unchanged unit folder, ignored for a
  `base:` source whose folder differs; `NamedTests()` when `named_task_text` is None (a fix unit).
- [x] 1.2 `tdd.py`: `preexisting_test_changes` takes `named`; a `changed` named test is exempt, `deleted`/`rebound`/
  `unparsable` are not; `classify_red` leaves a named test out of `regressed` (D2); the accepted attempt emits `tests.superseded {task, tests, criteria: [], reason:
  "named_by_task", source}` for the named tests red changed; the stale event gets `reason: "stale"`;
  `_PREEXISTING_ADVICE` gains its sentence (D2). Tests in `test_red_preexisting_tests.py` for SCN-IMP-400, 401, 402.
- [x] 1.3 The red prompt: the `# Existing tests this task changes in place` section (only when non-empty) from
  `prompt.py`, and the `red.md` rule line, version 13 (D2). Update every test that pins `red@12`. Tests in
  `test_prompt.py`: section present with the ids, absent with none (SCN-IMP-403).
- [x] 1.4 The verifier listing: integrity shows a `named_by_task` superseded test as `<id> (named by the task text,
  <source>)`; a stale one as today. Test in `tests/unit/verifier/` beside the existing superseded tests.

## 2. A named helper red creates (D3; L4-IMP-083)

- [x] 2.1 `guards.py`: `FrozenFile.added` from `--diff-filter=A`. `unfreeze.py`: `Grant.helper`, and the opening rule of
  D3 in `named_by_task`. Tests in `test_named_unfreeze.py` for SCN-IMP-405 (opened) and SCN-IMP-407 (kept reasons).
- [x] 2.2 `opened.py`: `check_filled_helper` with the texts of D3; `tdd._check_opened` uses it for a helper grant.
  Tests in `test_opened.py` (each text) and one bench test for SCN-IMP-406.

## 3. The zero-value run and the remedy (D4, D5; L4-IMP-084, L4-IMP-085)

- [x] 3.1 `tdd.py`: the union of D4; the docstring of `head_stub_modules`. Bench test for SCN-IMP-408.
- [x] 3.2 `discrimination.py`: `Vacuity.errors`, the three remedies of D5 from the zero run's error texts, and
  `Vacuity.message` using them. Tests in `test_vacuity.py` for SCN-IMP-409, SCN-IMP-410 and the AttributeError text,
  and one that an other error keeps today's text.

## 4. The clarifier (D6; L4-CLR-007)

- [x] 4.1 `clarifier/context.py`: the two rules, the signature excerpts, `PROMPT_VERSION = 6`. Tests in
  `test_context.py` for SCN-CLR-001, for a covered line (no duplicate excerpt) and for a name with no definition (no
  excerpt). Update tests that pin version 5.

## 5. Docs

- [ ] 5.1 `docs/SPEC.md`: the five requirements and their scenarios where the neighbouring ones are (L4-IMP-048 and
  L4-IMP-014 for 082/083, the vacuity requirements for 084/085, L4-CLR-006 for CLR-007), and change row 64
  `named-tests` in the table of changes (after row 63). `check_spec.py` clean.
- [ ] 5.2 The spec-writing guidance in `skills/` (the skill page that tells authors how to write tasks and criteria):
  to change an existing test, name it in the task line or the criterion as `path::name`; a helper the tests need goes
  in the task line by path. One short paragraph, no consumer names.
