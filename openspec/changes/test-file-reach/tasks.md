## 1. Find a test's file in any language, and show its own lines (L4-IMP-065)

- [x] 1.1 Tests first, then `src/l4/implementer/test_locate.py` (pure: no Workbench, no git):
  `file_of_id(test_id, paths, preferred=())` and `window(text, name)` as design D1 and D2 say. Unit tests in
  `tests/unit/implementer/test_test_locate.py`: the slash head, a dotted Python module (`tests.test_x.TestY::test_z` →
  `tests/test_x.py`), a dotted TypeScript head with dots in the file name (`src.pricing.total.v2.test.ts`), a head below
  the root (`pricing.total.test.ts` with `src/pricing/total.test.ts`), two matches (None; the preferred one wins), a
  `::` inside a test name; `window` for a top-level `test(…)`, an `it` inside `describe` named `total > adds` and
  `total adds`, a Go `func TestX(t *testing.T) {`, a block longer than 40 lines (cut by the caller, not by `window`), a
  missing name (None), `.only`/`.skip`/`.each` calls.

  Result: with no module, the 18 tests failed at import (`No module named 'l4.implementer.test_locate'`); with it they
  pass. `window` gives the block whole (the caller's `_cut` makes the 40-line cut, as this task says, so the
  `[cut: N more lines]` note stays true); it also reads a call whose name is on the next line (`it(` then the string),
  and Go's `func Name(` (a subtest `TestX/sub` is looked up by `TestX`).

- [x] 1.2 `held_patch`: `_test_path` falls back to `file_of_id` over `git ls-files -z --cached --others
  --exclude-standard` of the work tree, with the step's changed files as `preferred`, keeping its checks (a regular
  file, not a link, inside the work tree); `_raw_source` uses `window` for a file that is not Python and keeps the
  file-to-end text only when `window` finds nothing but a line holds the name; `[…]` is stripped only for `.py`; the
  name is the part after the first `::`. Tests in `tests/unit/implementer/test_held_accept.py` for SCN-IMP-413 and
  SCN-IMP-414 (a held test chore whose `.ts` test has its assertions after line 40 of the file; the question shows
  them; redaction still applies; the not-found text when the name is missing).

  Result: on the old code the two new tests failed with `(the source of this test was not found)` for the dotted
  TypeScript id. With the change they pass, and `_test_path` keeps its own two candidates first (the head as a path, the
  dotted Python module) and only then asks `file_of_id`. Where this differs from the task text: the "file to its end"
  fallback of `_raw_source` is kept for a Python file whose function is not found (as before), and is not reachable for
  a file that is not Python, because `window` already falls back to the first line that holds the name. The existing
  test `test_minor_a_non_python_test_is_redacted_before_the_cut` now indents the key inside its template literal: a
  block ends at the first line indented no deeper than its first line, so a column-0 line inside a template literal
  ends it.

## 2. The runs that cannot reach a test do not reject it (L4-VER-050)

- [x] 2.1 Tests first (`tests/unit/verifier/test_extra_inconclusive.py`, `tests/unit/implementer/test_criterion_tests_chore.py`),
  then `discrimination`: `NOT_PYTHON` and `NO_ZERO` texts; `ExtraRun.made`; in `discriminate_extra` the work tree's
  paths are listed once and each wanted test's file found with `file_of_id`; after the runs, a test not accepted whose
  file is found and is not `.py` and whose reason is not `ERROR_AT_BASE` is inconclusive with `NOT_PYTHON` (the file in
  the text); with `made` empty every test not accepted is inconclusive (`NO_RUN` when the scope and the production
  files were empty, else `NO_ZERO`). Tests: SCN-VER-243 (scope and production non-empty, runs faked to pass the `.ts`
  test: inconclusive with the file named), SCN-VER-244 (`zeroed_run` returns None, no production: `NO_ZERO`, no run),
  SCN-VER-246 (a Python test failing by assertion in the zero run is accepted as before), and a `.ts` test failing on
  the base by an error keeps `ERROR_AT_BASE`.

  Result: on the old code the new verifier tests failed on the missing `discrimination.worktree_files`, `NOT_PYTHON`,
  `NO_ZERO` and `ExtraRun.made`. With the change they pass (SCN-VER-243, 244, 246, the base-error case, and a Python
  test and a test whose file is not found keep today's rules). `worktree_files(wb)` (`git ls-files --cached --others
  --exclude-standard`) is new in `discrimination` and is listed once, only when a test is left open; `held_patch` now
  takes it from there instead of its own copy, so `held_patch` imports `discrimination`. The preferred files of
  `file_of_id` are the unit's own test files (`own`). `NOT_PYTHON` replaces a reason a test already had from the
  zero-value run (such as `did not run in test-extra-zero`) as the task text says, because the file is the cause the
  reader can act on. The tests that build a bare workbench now patch `worktree_files`. The chore-level tests of this
  task are in the 2.2 commit, because they assert `Runs:` through `outcome.made`.

- [x] 2.2 `tdd._discriminating_tests`: the hold's runs are `outcome.made`; with some added tests rejected and the others
  inconclusive, the reason lists only the rejected ones as passing both runs, then each inconclusive one with its reason
  (the existing `MAX_LISTED` cap on each list). Tests: SCN-VER-243 end to end through a chore (held, `Runs:` naming the
  runs made, no attempt used), SCN-VER-245 (the reason text), the zero-value-run-only case (`runs == ("test-extra-zero",)`).

  Result: on the old code the three new chore tests failed on the missing `discrimination.file_of_id` (they stand in for
  a reporter that gives a test an id in a file that is not Python: a pytest gate cannot report a `.ts` test, so
  `file_of_id` is replaced and the two extra runs are the real gates). With the change they pass: SCN-VER-243 end to
  end (held, `runs == ("test-extra-zero", "test-extra-base")`, both gates ran, no attempt used), the zero-value run
  only (`runs == ("test-extra-zero",)`, no base gate), and SCN-VER-245 (the attempt fails; the reason lists the rejected
  test before `Inconclusive, not counted as passing:` and the other one after it, with its reason).

- [ ] 2.3 Run `tests/unit/implementer`, `tests/unit/verifier`, `uv run ruff check .`, `uv run ruff format --check` on
  the changed files.

## 3. Docs (one pass at the end of the release)

- [ ] 3.1 `docs/SPEC.md`: L4-VER-050 and L4-IMP-065 as this change's spec says; SCN-VER-243 to SCN-VER-246 after
  SCN-VER-242; SCN-IMP-413 and SCN-IMP-414 after SCN-IMP-412; change-table row 82 `test-file-reach`; CHANGELOG 0.4.38
  under Fixed. `scripts/check_spec.py`, `tests/unit/docs`, `openspec validate test-file-reach --strict`.
