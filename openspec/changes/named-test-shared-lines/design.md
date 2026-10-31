# Design: a named test is also changed through its file's shared lines

## D1. The file's shared lines

`test_locate.outside_tests(text, names) -> str`: the lines of `text` that lie in no `window(text, name)` of `names`,
blank (whitespace-only) lines dropped, joined with `\n`. A name whose window is None (not found, ambiguous) removes
nothing. Pure.

Blank lines are dropped because a test appended to the file brings the blank line before it, which lies outside every
window. Comments outside the tests count: a changed comment is a change of the file, and it only matters when the named
test also fails.

## D2. Which named tests red changed

`named_other_changed(wb, base, named, base_report, report)` returns, in `named.other` order, the report id of each named
test of another language that red changed in place:

1. own lines: `window()` at the base and in the work tree are both found and differ (as before);
2. shared lines: both windows are found and equal, the id is in `report.tests` with status `failed` or `error`, and
   `outside_tests(base text, base names) != outside_tests(work-tree text, red names)`, where the base names are the test
   names (`id.partition("::")[2]`) of the base report's ids that `file_of_id` maps to the path, the red names those of
   the red report's ids, and the paths `file_of_id` reads are the base tree's (`ls-tree -r --name-only <base>`, read
   once per call).

A symlink or a missing file is skipped (as before). A shared-lines test is excused only when it fails, because a change
outside its lines cannot be attributed to it: a red step that adds a test and an import to the file and leaves the named
test passing changes nothing about the named test, and must not fail with `a test the task names was changed but does
not fail at red`. `classify_red` is unchanged for every id `named_other_changed` returns: `_unfit` still requires an
assertion or `NotImplementedError` (no hang), and a deleted or renamed id stays `red broke existing tests`.

The Python path is unchanged: L4-IMP-046's closure makes a changed module-level definition a change of every test that
reaches it, so a named Python test is already changed through its file's definitions (and another test of the file that
reaches the same definition is rejected as tampered). For another language the other tests of the file are only
protected by the regression check and by step 1 (which runs the base version of the file), as before.

## D3. The reason when nothing of the file changed

`classify_red(..., named_unchanged=...)`: the named ids of another language that fail at red and that
`named_other_changed` did not return. When the attempt fails as `red broke existing tests` and one of them is among the
regressed ids, the reason gets `; the task names <id>, but red changed neither its lines nor the lines of its file
outside the tests: change the test, or a constant or helper of its own file that it reads` (the first one, bounded like
the other ids). The order of the checks of `classify_red` does not change.

## D4. The record

Before the agent step of each red attempt, when the reviewed text names at least one test (either kind),
`named_tests.found{task, tests, source}` is recorded: `tests` the Python `path::name` ids and the other ids, as the red
prompt lists them (`named_listing`), `source` the reviewed text's source. The event exists because only the failure
(`named_tests.kept`) and the success (`tests.superseded`) were recorded, so a red step that failed on a named test left
no sign that the test had been named.

## D5. The judge

`judge.NamedChange` gets `file_diff: str = ""`. `ladder._named_changes`, for a test of another language whose lines at
the base and at head are both found and equal, sets `file_diff` to the unified diff of its file between the base and
head (`difflib.unified_diff`, 3 lines of context, labels `a/<path>` and `b/<path>`). `_named_lines` then renders, under
the test's line, `its own lines are the same at the base and at head; red changed it through its file (shared
constants, fixtures or helpers):` and the diff, cut by `_cut_window`, instead of the two equal versions. The block stays
in the user text: `SYSTEM` and `PROMPT_VERSION` (13) are unchanged, so the template lock stays valid.

## D6. The red prompt

`_named_section` adds to its first paragraph: `A change counts when it is in the test's own lines or in its file outside
every test (a constant, fixture or helper of that file that the test reads); a change in another file does not, and
the file's other tests must still pass.` `red.md` is not changed (the section is code), so the template stays `red@13`.
