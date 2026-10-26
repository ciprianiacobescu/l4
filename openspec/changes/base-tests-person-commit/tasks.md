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
