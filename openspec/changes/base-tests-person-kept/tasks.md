## 1. A file a person changed last stays at head for the run (L4-VER-038)

- [x] 1.1 Tests first, in `tests/unit/verifier/test_base_tests.py`, next to
  `test_support_files_changed_by_infra_or_people_are_kept_at_head` (reuse its helpers: `new_repo`, `repo.write`,
  `repo.commit(..., task=..., tdd=...)` for a harness commit, `repo.commit_as_human(...)` for a person's,
  `repo.context(base, head, tasks=...)`, `kept_files(ctx, paths)`, `ScriptedWb`, `passing_report`, `check_base_tests`;
  read `allow_repo` and the tests around it first):
  - `test_a_file_a_person_changed_last_is_kept_at_head`: a harness commit (`tdd="red"`, task 1.1) changes
    `tests/test_a.py`, then a person's commit changes it again; `kept_files(ctx, ["tests/test_a.py"])` keeps it with
    exactly `people changed it last (<sha1>, <sha2>)`, the two commits' 10-character shas, harness first.
  - `test_a_harness_commit_after_the_persons_puts_it_back`: a person's commit changes `tests/test_a.py`, then a harness
    commit (`tdd="green"`, task 1.1) changes it again; `kept_files` does not keep it.
  - `test_the_run_keeps_a_person_last_file_at_head_as_a_persons_line`: with the first set-up and a passing scripted
    report, `check_base_tests` has no finding, the `verify.base_tests` event's `reverted` does not list
    `tests/test_a.py`, and `out.human_tests` has a line that starts with `tests/test_a.py kept at head for the run` and
    contains `people changed it last` (SCN-VER-241).
  - the existing tests keep passing unchanged (`test_support_files_changed_by_infra_or_people_are_kept_at_head`: the
    agent-only `tests/test_render.py` is still put back).

  Then in `l4.verifier.base_tests.kept_files`, after the `_allowance` branch, add the branch of design D1 (import
  `_last_by_people` from `l4.verifier.integrity` next to the names already imported from it) and update the docstring
  (a file a person changed last also stays). Do not change `_by_people`, `split_allowed` or the `"people" in why`
  filter of `check_base_tests`. Run `tests/unit/verifier`.

  Result: on the old code `test_a_file_a_person_changed_last_is_kept_at_head` failed (`kept_files` returned `{}` instead
  of `people changed it last (<red sha>, <person sha>)`) and `test_the_run_keeps_a_person_last_file_at_head_as_a_persons_line`
  failed (`reverted` was `['tests/test_a.py', 'tests/test_b.py']`, not `['tests/test_b.py']`);
  `test_a_harness_commit_after_the_persons_puts_it_back` passed before and after (the guard against a rule that is too
  loose). All three pass with the `_last_by_people` branch in `kept_files`, the existing kept-file tests are unchanged
  and pass, and `tests/unit/verifier` is green.
- [ ] 1.2 Docs:
  - `docs/SPEC.md`, L4-VER-038, its last sentence "A support file only people changed, a `[test-infra]` task changed or
    a `task.unfrozen` frees SHALL stay at head for the run, listed." becomes "A test or support file that only people
    changed, that a `[test-infra]` task changed, that a `task.unfrozen` frees, or whose last change in `base..head` is
    a person's commit SHALL stay at head for the run, listed; the last kind as a person's line that names every commit
    that changed it, the harness's included, and a harness commit after the person's puts the file back."
  - `docs/SPEC.md`: after SCN-VER-240, `#### SCN-VER-241 (+) A file a person changed last stays at head for the run ·
    L4-VER-038, L4-IMP-081`, Given/When/Then as the spec delta's scenarios in one (a harness red commit and then a
    person's commit changed `pkg/a_test.go`; a person's commit and then a harness green commit changed `pkg/b_test.go`;
    `tests/test_meta.py`, unchanged, runs the package's tests → `pkg/a_test.go` stays at head as a person's line that
    names both commits, `pkg/b_test.go` is put back, and the meta test passes with the head version of
    `pkg/a_test.go`).
  - `docs/SPEC.md` change table: row 80 `base-tests-person-kept` after row 79, in the form of rows 76 and 79 (what
    changed; the cause: a Go unit's fix unit stopped again after the person's commit that L4-IMP-081 asks for, because
    an acceptance test the unit did not change runs the package's Go tests and ran the base version of the person's
    file; `openspec/changes/base-tests-person-kept/`; checked by `test_base_tests` and a unit stopped this way that
    passes step 1 on its next run).
  - `CHANGELOG.md`: `## 0.4.36 (unreleased)` above `## 0.4.35 (2026-10-27)`, `### Fixed`: in step 1 of the verifier, a
    test or support file whose last change is a person's commit now runs at head, not at its base version, so a test
    the unit did not change that runs it (a wrapper around the package's test runner) no longer fails on the content
    the person replaced; it is listed as a person's line naming every commit that changed it (L4-VER-038).
  - if a docs test pins the scenario range of the verifier's 0.4.33 scenarios (grep `SCN-VER-239`, `range(2` in
    `tests/unit/docs`), widen it the way earlier changes did.
  Run `uv run python scripts/check_spec.py docs/SPEC.md` and `uv run pytest tests/unit/docs tests/unit/test_release_notes.py -q`.
