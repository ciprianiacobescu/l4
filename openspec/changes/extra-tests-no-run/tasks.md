## 1. A test no run can vary is inconclusive (L4-VER-050)

- [x] 1.1 Tests first:
  - `tests/unit/verifier/test_extra_inconclusive.py`, with a helper `nothing_to_vary(monkeypatch)` that makes
    `imported_modules` and `_changed_modules` empty, `production_changes` `[]`, and `zeroed_run` and
    `run_with_code_of` raise (no run may be made):
    - `test_scn_ver_242_an_extra_test_no_run_could_be_made_for_is_inconclusive`: a TypeScript test id and a Python one
      are rejected and inconclusive with `discrimination.NO_RUN`, `runs == 0`, no `reasons`;
    - `test_the_ladder_says_why_no_run_could_be_made`: `ladder._extra_proof_step` through the real
      `discriminate_extra` gives the TypeScript test the reason `inconclusive: <NO_RUN>` and no proof.
  - `tests/unit/implementer/test_criterion_tests_chore.py`:
    `test_a_chore_whose_tests_no_run_can_vary_is_held_with_no_runs`: the same three collectors made empty, a test chore
    citing a criterion through the real `discriminate_extra` is held (`check == "tests"`), its reason is `NO_RUN`, its
    `runs` is `()`, no `test-extra-*` gate ran, nothing is committed and no `task.tests_added` is recorded.

  Then in `l4.implementer.discrimination.discriminate_extra`, compute `production_changes` before the zero-value run
  and, when there are tests and neither the scope nor `production` has a file, return
  `ExtraRun(rejected=wanted, inconclusive={test: NO_RUN})` (design D1); in `l4.implementer.tdd._discriminating_tests`,
  name the two runs in the hold only when `outcome.runs` is above 0 (design D3). Update both docstrings and
  `ExtraRun`'s.

  Result: on the old code the three new tests failed, the verifier ones on `NO_RUN` (the outcome had no `inconclusive`
  entry: every id was only rejected) and the chore one by assertion (`'failed' == 'held'`: the attempt failed with
  `none of the tests you added looks at the answer`). With the change all pass, and `test_extra_inconclusive`,
  `test_criterion_tests_chore`, `test_held_accept`, `test_held_answers`, `test_held_check`, `test_tdd_red`,
  `test_planted_links_verifier`, `test_ladder` and `test_single_phase` pass.
- [x] 1.2 Docs:
  - `docs/SPEC.md`, L4-VER-050: after "A test chore whose added tests are all inconclusive SHALL be held …", the case
    of no run: both runs vary Python files only; when neither can be made every such test is inconclusive with that
    reason and no gate run, its minor finding says `inconclusive: neither run could be made: …`, and a test chore of
    such tests is held with `Runs:` `none`; it is not rejected as a test that passes both runs.
  - `docs/SPEC.md`: after SCN-VER-241, `#### SCN-VER-242 (−) A test no run can vary is inconclusive; its chore is held ·
    L4-VER-050, L4-VER-009, L4-IMP-063`.
  - `docs/SPEC.md` change table: row 81 `extra-tests-no-run` after row 80.
  - `CHANGELOG.md`: `## 0.4.37 (unreleased)` above `## 0.4.36 (2026-10-27)`, `### Fixed`.
  Run `uv run python scripts/check_spec.py docs/SPEC.md`, `uv run pytest tests/unit/docs tests/unit/test_release_notes.py
  -q`, `uv run ruff check .` and `openspec validate extra-tests-no-run`.
- [x] 1.3 Review: step 4 takes only a test whose file is a Python file (`ladder._extra_proof_step` keeps a test only
  when `file_of_test` finds its file, and `_test_file` finds `.py` files only), so a TypeScript test never reaches
  `discriminate_extra` there and keeps its `no proof` finding. `test_the_ladder_says_why_no_run_could_be_made` now uses
  a Python test (it patched `file_of_test` to give a `.ts` file, a case step 4 never has), and
  `test_a_test_in_another_language_is_no_step_4_candidate` checks the real `file_of_test` with a `.ts` file. L4-VER-050,
  SCN-VER-242, row 81, CHANGELOG, this change's spec, proposal and design (D4, D5: the mixed-language residual) say so.
  The chore's docstring says its `Runs:` line names both runs when a run was made.
