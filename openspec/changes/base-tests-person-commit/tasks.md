## 1. A person's last commit to a test file excuses its failing base tests (L4-VER-038, L4-IMP-081)

- [x] 1.1 Tests first, in `tests/unit/verifier/test_base_tests.py`, next to
  `test_the_allowances_cover_superseded_unfrozen_infra_and_people_files` (reuse its helpers: `new_repo`,
  `repo.write`, `repo.commit(..., task=..., tdd=...)` for a harness commit, `repo.commit_as_human(...)` for a
  person's, `repo.context(base, head, tasks=...)`, `split_allowed(ctx, ids)`):
  - `test_a_persons_commit_after_the_harness_red_step_is_a_persons_line`: a harness commit (`tdd="red"`, task 1.1)
    changes `tests/test_a.py`, then a person's commit changes it again; `split_allowed(ctx, ["tests.test_a::test_a"])`
    returns no blocked id, no allowed line and one person's line that starts with
    `tests.test_a::test_a fails with the base version` and names both commits' 10-character shas.
  - `test_a_harness_commit_after_the_persons_keeps_the_blocker`: a person's commit changes `tests/test_a.py`, then a
    harness commit (`tdd="green"`, task 1.1) changes it again; the id is blocked and there is no person's line.
  - the existing test keeps passing unchanged (only people changed `tests/test_d.py`: a person's line; the harness
    alone changed `tests/test_e.py`: blocked).

  Then:
  - in `l4.verifier.integrity`, next to `_by_people`, add `_last_by_people(commits_: list[list[str]]) -> bool`: true
    when the list is not empty and its last record is not the harness's (`not is_harness(commits_[-1])`), with a
    docstring that says the last commit set the content the base-test run judges, and that nobody found is not people;
  - in `l4.verifier.base_tests.split_allowed`, use `_last_by_people` instead of `_by_people` for the person's branch
    (import it with the other `integrity` names); the line text and the order of the allowances stay as they are;
    update `split_allowed`'s docstring ("People's: a file whose last change in `base..head` is a person's commit; the
    line names every commit that changed it") and the module docstring's "only people's commits cover its file" to
    "a person's commit is the last to change its file";
  - `_by_people`, `kept_files` and every other caller stay as they are.

  The two new tests must fail before the change (the first: blocked instead of a person's line) and pass after; the
  second passes before and after (it is the guard against a predicate that is too loose). Run
  `tests/unit/verifier/test_base_tests.py`, `tests/unit/verifier/test_ladder_tamper.py` and `tests/unit/verifier`.

  Result: `test_a_persons_commit_after_the_harness_red_step_is_a_persons_line` failed on the old code (the id came back
  blocked instead of as a person's line) and `test_a_harness_commit_after_the_persons_keeps_the_blocker` passed; both
  pass with `_last_by_people` in `split_allowed`, the existing allowance test is unchanged and passes, and
  `tests/unit/verifier` is green.
- [x] 1.2 Docs:
  - `docs/SPEC.md`, L4-VER-038: replace "One that fails twice, does not run or no longer collects SHALL be a blocker,
    unless `tests.superseded` names it." with a sentence that lists the four allowances: `tests.superseded` names it, a
    `task.unfrozen` of the unit frees its file, a `[test-infra]` task's commit changed its file, or the last commit of
    `base..head` that changed its file is a person's (not the harness's under the author rule); the first three are
    listed as allowed, the fourth as a person's line that names every commit that changed the file, the harness's
    included; a harness commit after the person's keeps the blocker. Keep the sentence on support files that stay at
    head ("only people changed": unchanged).
  - `docs/SPEC.md`, L4-IMP-081: after "SHALL say that a person must commit that change on the unit branch", add that
    step 1 of the verifier reads that commit (L4-VER-038: a person's last commit to the file).
  - `docs/SPEC.md`: add after SCN-VER-238 (before `## MODIFIED Requirements`)
    `#### SCN-VER-239 (+) A person's last commit to a test file excuses its failing base test · L4-VER-038, L4-IMP-081`
    with Given (a harness red commit changed `tests/test_a.py` and a later person's commit changed it again; another
    file a person changed and a harness green commit changed after), When (step 1 runs and both files' base tests
    fail with their base versions), Then (the first is a person's line that names both commits, the second a blocker).
  - `docs/SPEC.md` change table: row 76 (`base-tests-person-commit`) after row 75, in the form of rows 74 and 75: what
    changed, the cause (a Go unit whose reviewed spec changed two existing tests escalated `same_failure` because the
    red commit made the file "not only people's" and the fix chores' edits are put back), the requirements, the
    folder, and how it is checked (the unit tests `test_base_tests`; a unit stopped this way passes step 1 after a
    person commits the test files and `l4 retry`).
  - `CHANGELOG.md`: `## 0.4.33 (unreleased)` above 0.4.32 with a `### Fixed` line: a person's commit to a test file on
    the unit branch, the way L4-IMP-081 names for a test a fix chore may not change, now clears the verifier's
    `a pre-existing test fails on the unit's code` blocker even when a harness step changed the file before; the
    person's line names every commit that changed it (L4-VER-038).

  Run `uv run python scripts/check_spec.py docs/SPEC.md` and the docs tests (`uv run pytest tests/unit/docs -q`).

  Result: L4-VER-038, L4-IMP-081, SCN-VER-239, change-table row 76 and CHANGELOG 0.4.33 are written; `check_spec.py`
  is clean and `tests/unit/docs` passes (120).

## 2. Step 1 finds the file of a Go test (L4-VER-038)

- [ ] 2.1 Tests first, in `tests/unit/verifier/test_base_tests.py`, after the two tests of 1.1 (same helpers; the repo
  holds `apps/x/go.mod` with the text `module example.com/services/x\n\ngo 1.22\n`, so the module path is NOT the
  directory, and `apps/x/internal/server/a_test.go` with `package server\n\nimport "testing"\n\nfunc TestA(t *testing.T) {}\n`
  at the base):
  - `test_a_go_test_whose_module_path_is_not_its_directory_is_a_persons_line`: a harness commit (`tdd="red"`, task 1.1)
    changes `apps/x/internal/server/a_test.go`, then a person's commit changes it again;
    `split_allowed(ctx, ["example.com/services/x/internal/server::TestA"])` returns no blocked id, no allowed line and
    one person's line that starts with `example.com/services/x/internal/server::TestA fails with the base version` and
    names both commits' 10-character shas;
  - `test_a_go_subtest_takes_the_file_of_its_function`: the same history; the id
    `example.com/services/x/internal/server::TestA/case_one` is a person's line too;
  - `test_a_go_test_no_file_declares_is_blocked`: the same history; `example.com/services/x/internal/server::TestMissing`
    is blocked; and `example.com/other::TestA` (no module path starts it) is blocked;
  - `test_a_go_test_declared_in_two_files_is_blocked`: a second file `apps/x/internal/server/b_test.go` at the base also
    declares `func TestA(` (in `package server_test`); the same history on `a_test.go`; the id is blocked;
  - `test_a_go_test_in_a_directory_below_is_not_the_packages`: `TestA` is declared only in
    `apps/x/internal/server/sub/a_test.go` (the package `.../server/sub`); with the same history on that file, the id
    `example.com/services/x/internal/server::TestA` is blocked.

  Then, in `l4.verifier.base_tests`, extend `_file_of` (keep its pytest loop first and unchanged): when the loop finds
  nothing and the id has `::`, call a new `_go_file_of(ctx, classname, name)` that, for `rev` in
  `(ctx.head_sha, ctx.base_sha)`:
  1. lists the tree with `ctx.git.run("ls-tree", "-r", "--name-only", rev, check=False).stdout.splitlines()`;
  2. for each path that is `go.mod` or ends with `/go.mod`, reads its text (`_text(ctx.git, rev, path)`, import it
     from `l4.verifier.integrity` with the other names) and takes the module path of its first line that matches
     `^\s*module\s+(\S+)` (strip surrounding `"` quotes); a module matches when `classname == module` or
     `classname.startswith(module + "/")`; take the longest matching module;
  3. the package directory is the `go.mod`'s directory (`""` for the root) joined with `classname[len(module):]`
     without its leading `/` (use `posixpath.join`, and drop an empty part, so the root module's package at the root
     is `""`);
  4. among the tree's paths whose `posixpath.dirname` equals that directory and that end with `_test.go`, keeps those
     whose text has a line matching `^func\s+<re.escape(name.split("/", 1)[0])>\s*\(` (multiline);
  5. exactly one such file: return it; else go on to the next revision. Return None when no revision gives one.

  Give `_go_file_of` a docstring in the style of the module (gotestsum's JUnit id `<import path>::<TestName>[/<case>]`;
  the module path is the `go.mod`'s `module` line and need not match its directory; one declaring file or none). Update
  `_file_of`'s docstring to name both rules. Nothing else changes; `_collection_lines` keeps calling `_file_of`.

  The five new tests must fail before the change except `..._no_file_declares_is_blocked`,
  `..._declared_in_two_files_is_blocked` and `..._in_a_directory_below_is_not_the_packages` (blocked before and after:
  the guards), and all pass after. Run `tests/unit/verifier/test_base_tests.py` and
  `tests/unit/verifier/test_ladder_tamper.py`; `ruff check` and `ruff format --check` on the changed files.
- [ ] 2.2 Docs:
  - `docs/SPEC.md`, L4-VER-038: after the sentence that ends "a harness commit after the person's keeps the blocker.",
    add: "A test's file SHALL be found from its id: a pytest id from its dotted module (`tests.test_x.TestY::test_z` is
    `tests/test_x.py`), a Go id (`<import path>::<name>`) as the one `*_test.go` file directly in the package's
    directory that declares `func <name up to the first />(`, the directory found from the `module` line of the
    `go.mod` whose module path is the longest prefix of the import path, at head and then at the base; a test with no
    file, or with more than one, has none of the three allowances that read a file."
  - `docs/SPEC.md`: add after SCN-VER-239
    `#### SCN-VER-240 (+) A Go test's file is found from its module · L4-VER-038` with Given (`apps/x/go.mod` says
    `module example.com/services/x`; a harness red commit and then a person's commit changed
    `apps/x/internal/server/a_test.go`, which declares `func TestA(`), When (step 1 runs and
    `example.com/services/x/internal/server::TestA` and `example.com/services/x/internal/server::TestB` fail with their
    base versions, and no file declares `func TestB(`), Then (the first is a person's line that names both commits, the
    second a blocker).
  - `docs/SPEC.md` change table, row 76: in the "what changed" cell, after "the harness's included, and a harness
    commit after the person's keeps the blocker;", add "a Go test's file is found from its id (the `*_test.go` file of
    the package that declares the function, the package's directory from the `module` line of its `go.mod`), so the
    allowances that read a file work for Go;"; in the cause, after "could not clear the blocker", add "and a Go test id
    had no file, so no allowance that reads one could apply".
  - `CHANGELOG.md`, the 0.4.33 Fixed entry: add a sentence at its end: "Step 1 also finds the file of a Go test (the
    `*_test.go` file of its package that declares the function, the package found from the `module` line of its
    `go.mod`), so this and the `task.unfrozen` and `[test-infra]` allowances work for Go tests."

  Run `uv run python scripts/check_spec.py docs/SPEC.md` and `uv run pytest tests/unit/docs -q`.
