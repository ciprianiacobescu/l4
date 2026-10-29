# Design: named-test-any-language

## Context (verified on amaster e66cde82, read-only analysis of 2026-10-30)

- `named_tests._NODE` matches `<path>.py::name` only; candidate files are `.py`; `test_id`/`names_test_id` build Python
  ids. `run_red` builds `base_report` before it resolves named tests.
- `classify_red` rejects an existing test that red changed ("red broke existing tests") unless L4-IMP-082 names it.
- `test_locate.file_of_id(test_id, paths, preferred)` maps a report id (dotted `src.pricing.total.test.ts::…` or plain
  `src/list.test.ts::…`) to its file; `window(text, name)` gives a test's source lines.
- A file red changed becomes a frozen red test for green; `green_failures` requires every base-passing test to pass;
  step 1 runs the file at its base version and excuses only exactly named ids (`base_tests`).
- The judge sees the diff and answers but no block names a test-edit exception (judge.py `_owner_changes` is a model).

## D1 The token and its resolution

In `named_tests`, a second pattern for a backticked `path::name` whose path is not `.py`; the path must be tracked,
regular (not a symlink), match `tdd.test_globs` and no support/ignore glob, and appear in the task's reviewed text
(`named_task_text`). Resolve against `base_report`: the ids whose `file_of_id` is that path and whose test-name part
equals the given name or ends with it after a separator (` > `, `.`, ` `); exactly one → named; zero or several → kept
with `no test of that name in the base report` / `more than one test matches`.

## D2 Red

`classify_red` excuses a named non-Python id when it is still in the red report and its `window()` differs between the
base and red file contents. Such a changed test that passes at red fails the attempt: `a test the task names was
changed but does not fail at red: <id>` (the change must assert something the code does not do yet). Deleted or
renamed: rejected as today. Record `tests.superseded{task, tests: [ids], criteria: [], reason: "named_by_task", source,
language}` as the Python path does.

## D3 The judge

A block in the judge prompt, beside the owner changes, listing the named tests red changed in place with their ids and
`source` ("the reviewed task names these tests; red changed them; green made them pass").

## D4 Not changed

Green opens no pre-existing test of any language (D3 of unfreeze-and-answer); L4-IMP-014's kept reasons; L4-IMP-016;
the Python forms; the answer route; `kept_files`.
