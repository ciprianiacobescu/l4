## 1. The token and red (L4-IMP-089)

- [x] 1.1 Write the tests first (tests/unit/implementer/test_named_tests.py, test_red_preexisting_tests.py,
  test_tdd_red.py, test_test_locate.py; tests/unit/verifier/test_base_tests.py with its fake runner for TS JUnit
  reports, test_integrity_superseded.py). Then implement design D1 and D2. Cases: SCN-IMP-439 to SCN-IMP-444, both id
  forms (dotted and plain path), the kept reason of unfreeze's support-file rule unchanged.
  Result: `named_tests.find_named_other` reads a whole backticked `path::name` (split at the first `::`; the name may
  hold spaces, ids and punctuation) and resolves it against the base report: `file_of_id` must give the path and the
  report's test name must equal the given name or end with it after ` > `; one match names the test, none or several
  are kept (`no test of that name in the base report`, `more than one test matches`), and so is a test whose lines
  `window()` cannot find. `named_tests` takes the base report; the cap of 5 counts both kinds. `classify_red` takes
  `named_other`: a changed named id still in the red report is no regression, one that does not fail fails the attempt
  (`a test the task names was changed but does not fail at red: <id>`), one gone from the report is `red broke
  existing tests`. `run_red` finds the changed ones by comparing `window()` at the base and in the work tree, records
  `tests.superseded{reason: named_by_task, source, language}` (the Python event now carries `language: "python"`) and
  lists the tests in the red prompt. Deviation from D1: only ` > ` is a separator (not `.` or a space), so a short
  name cannot match the tail of a longer one. Step 1 needed no code: it already excuses the recorded id and reports
  the rest of the file (SCN-IMP-444 is pinned by a test). Unfreeze is untouched, so its kept reasons are as before.

## 2. The judge (L4-VER-068)

- [x] 2.1 Write the test first (the judge prompt tests under tests/unit/verifier; grep `Owner changes`). Then add the
  block of design D3. Case: SCN-VER-253.
  Result: `build_judge_prompt` takes `named_changes` ((test id, source) pairs) and renders a block `## Named tests
  changed in place` beside the owner changes (a data block, 40 lines at most); `ladder._named_changes` reads them from
  the `tests.superseded{reason: named_by_task}` events, once per id, Python and other languages alike. The block lives
  in the user text only: `SYSTEM` and `PROMPT_VERSION` (13) are unchanged, so the template lock stays valid.

## 3. Checks

- [x] 3.1 Run only the test files you changed or added, once each, then ruff check and ruff format on the changed
  files. Report the counts.
  Result: test_named_tests, test_red_preexisting_tests, test_tdd_red, test_test_locate, test_base_tests and
  test_integrity_superseded ran together: 170 passed; test_prompt and test_judge_step: 45 passed. ruff check and
  ruff format --check pass on the 12 changed Python files.
