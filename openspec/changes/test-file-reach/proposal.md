# A test in a file of another language is found, and the runs that cannot reach it do not reject it

## Why

Release 0.4.37 made a test chore in a project whose code is not Python held instead of failed, when neither of the
two runs of `discriminate_extra` (the zero-value run and the base run, L4-VER-050) could be made. Three cases of the
same kind remain, and one more gap showed in the first question that release raised [V, a consumer's TypeScript
delivery plan, 2026-10-28]:

1. **A project with code in Python and in another language.** When the unit changed a Python production file (for
   example a deploy script `deploy/seed.py`), the runs are made, but they vary Python files only. A TypeScript test
   such as `src/pricing/total.test.ts` does not load them, so it passes both runs and is rejected with `none of the
   tests you added looks at the answer`, whatever it asserts. The unit halts on `max_task_attempts` as before 0.4.37.
2. **No run made for another reason.** When the zero-value scope has files but no function in them can be varied
   (`zeroed_run` returns None: the files cannot be read or parsed) and the unit changed no Python production file, no
   run is made, yet the tests are rejected with the same text.
3. **The hold names runs that were not made.** The hold of a test chore names both runs whenever one run was made,
   also when only the zero-value run was made (the base run needs a changed Python production file).
4. **The question does not show the test.** The held question of the consumer's test chore printed `(the source of
   this test was not found)` for both TypeScript tests. The id of a JavaScript or TypeScript report is the test file's
   path with dots for slashes, `::`, and the test's full name (`src.pricing.total.test.ts::C-0a1b2c3d total of two
   prices`). `held_patch._test_path` tries that head as a path, or as a dotted Python module (`….py`), so it never
   finds `src/pricing/total.test.ts`. The question's diff of the added file was cut after its first 40 lines (imports
   and helpers), so every assertion was in the cut part: who answers from the question alone sees no assertion.
   L4-IMP-065 already requires the source of each named test.

## What changes

- New `l4.implementer.test_locate`: `file_of_id(test_id, paths, preferred=())` finds a test's file among the
  repository's files from the id's head, in this order: (1) the head as a path; (2) the one file whose path with dots
  for slashes is the head; (3) the dotted Python module; (4) the one file whose path with dots for slashes ends with
  `.` + the head. Several matches at step 2 or 4 give None, unless exactly one of them is in `preferred`.
  `window(text, name)` gives a test's own lines in a file that is not Python: from the line of the test call that
  names it to the line that closes it (the first later non-blank line indented no deeper than that line, included
  when it only closes). It skips lines inside an unclosed template literal, and it tells equal test names in two
  `describe` blocks apart by the enclosing names, or gives none.
- `discrimination.worktree_files(wb)` lists the work tree's files, tracked and untracked, with the harness's excludes
  (`node_modules/`, its output folders). The list is made once for all the tests of a check, and once for all the
  tests and digests of a capture. A git failure gives no file, and so the not-found text.
- `held_patch`: `_test_path` asks only `file_of_id` (the step's changed files preferred); `_raw_source` redacts a file
  that is not Python whole before it takes the test's window (a window that ended inside a multi-line secret would show
  the part before its end), and uses `window` for it. A test name keeps a `::` in it, and `[…]` is taken off only for
  a Python file. The question shows at most 40 lines of the window.
- `discriminate_extra`:
  - a test that no run accepted, whose file `file_of_id` finds and ends with an extension of `OTHER_LANGUAGES`
    (`.ts`, `.js`, `.go`, `.java`, `.swift`, …), and that neither run reached by an error (it did not fail on the base
    by an error, and not by an error in the zero-value run), is inconclusive with `NOT_PYTHON` (`the zero-value run
    and the base run vary Python files only, and <file> is not a Python file`), not rejected. A reason that a run
    already gave is kept. A pytest doctest in a Markdown file is not in `OTHER_LANGUAGES`: the runs decide it;
  - when no run was made, every test that is not accepted is inconclusive: `NO_RUN` as before when there was nothing to
    vary, `NO_ZERO` (`no run could be made: no file of the zero-value scope could be varied, and the unit changed no
    Python production file`) when the zero-value scope had files but none could be varied;
  - `ExtraRun.made` names the runs made (`test-extra-zero`, `test-extra-base`).
- `_discriminating_tests`: the hold names `outcome.made`. When some added tests are rejected and the others
  inconclusive, the failure text names only the runs made, lists only the rejected tests as passing them, and lists the
  inconclusive ones apart with their reason.

## Impact

- Code: `l4.implementer.test_locate` (new), `l4.implementer.held_patch`, `l4.implementer.discrimination`,
  `l4.implementer.tdd`.
- Behaviour: a test chore of tests in another language is held (no attempt used) instead of failed in a mixed project
  too; a Python project's runs and outcomes do not change, except that a Python test is now inconclusive instead of
  rejected when no run at all could be made (case 2). Step 4 of the verifier keeps taking only Python test files
  (`file_of_test`), so a test in another language keeps its `no proof` finding there.
- `source_sha256` of a held step (audit only) changes for a test in another language, because its source is now the
  test's own lines.
- Docs: L4-VER-050 and L4-IMP-065 (docs/SPEC.md), scenarios SCN-VER-243 to SCN-VER-245 and SCN-IMP-413 to SCN-IMP-414,
  change-table row 82, CHANGELOG 0.4.38.
