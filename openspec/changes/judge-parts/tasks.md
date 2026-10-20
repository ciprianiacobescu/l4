Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, key, event and signature is in `design.md` (D1
  to D9 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree (`judge-parts`), with its own `.venv`. Never change git configuration. Never
  push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `judge-parts <n.m>: …`, with no
  trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- Name a consumer repository only as "a consumer repository". Put no local path in docs or fixtures.
- One implementer does the tasks in order, on top of the previous commits.
- The existing two-part worlds must keep their call counts: `tests/unit/verifier/test_judge_step.py` (its replies pass
  every criterion, and its `VerifyResult` has no trace, so no criterion is split) and
  `tests/unit/verifier/test_judge_parts_merge.py` (`merge_part_verdicts` is not changed).

Test worlds: `tests/unit/verifier/conftest.py` (`judge_reply(ids, verdict, **over)`, `make_bench`);
`tests/unit/verifier/test_judge_step.py` (`parts_bench(make_bench, monkeypatch, files, *results, cap=…, limit=…)`,
`_body`, `replies`, `judge_events`, `FOUR`; `wb.commit(..., task=…)` writes the `L4-Task` trailer);
`tests/unit/verifier/test_judge_run.py` (`Scripted`, `ok`); `tests/unit/verifier/test_diffparts.py` (entries and
`pack`); `tests/unit/verifier/test_judge_parts_merge.py` (part replies).

## 1. The follow-up module (design D2, D3, D4, D7, D8; L4-VER-056 to L4-VER-058)

- [x] 1.1 The files of a criterion and the split test. Tests first, new `tests/unit/verifier/test_judge_followup.py`:
  `test_the_files_come_in_order_from_the_records_and_the_diff_only` (SCN-VER-193: dotted pytest ids, `tests.test_report::test_header` and a bare `test_header`; the exact tuple `("src/app/export.py", "tests/test_report.py", "src/app/report.py", "src/app/format.py")`, and none of `docs/old.md`, `src/app/util.py`, `.l4/ledger/r1.jsonl`, `tasks.md`);
`test_a_dotted_pytest_id_resolves_to_its_file` (`packages.api.tests.test_x::test_y` with `packages/api/tests/test_x.py` in the diff resolves to it, as does `tests.test_x::TestK::test_y`; the id is never cut at its first `::` and read as a path);
`test_a_task_tick_of_tasks_md_never_makes_a_criterion_split` (SCN-VER-191: the task's commits also tick the unit folder's `tasks.md`, held in part 2, and C-2 is still not split; `tasks.md` and every harness or spec path are not among C-2's files); `test_a_reference_names_the_longest_diff_path` (`src/app/a.py:3` with `src/app/a.py` and
  `src/app/a.py.bak` in the diff, `tests/t.py::test_x`, a bare `test_x`);
  `test_task_files_reads_the_task_commits_of_the_family` (a scratch repository with commits of `L4-Unit` U and `L4-Task`
  1.2, of another unit with `L4-Task` 1.2, and a person's commit: only the first's files; one `git log` call, then one
  `git diff-tree` per matching commit); `test_the_tasks_of_a_criterion_come_from_red_ok_criteria` (`proof_tasks` over `task.red_ok` events with `criteria` `{C-1: {tests: [...]}, C-2: {}}`: the task is a task of C-1 only; a fix-unit event is skipped; a proof with only `discriminating` counts);
  `test_a_criterion_is_split_only_when_all_five_hold` (SCN-VER-190, SCN-VER-191, SCN-VER-192, SCN-VER-196: two parts, `insufficient_evidence`, no person's verdict, covered and not held after the parts' adequacy is applied, files in parts 1 and 2: split; one part's diff, a merged `pass`, `fail` or `not_verifiable`, a person's verdict, uncovered, held, a criterion whose only passing tracing test the parts called inadequate, files in one part, files in no judged part: not split; a cut part counts as its part); `test_no_git_command_without_a_candidate` (SCN-VER-193: a merged verdict with no covered
  `insufficient_evidence`: `files_of` and `task_files` are never called). Code: new `src/l4/verifier/judge_followup.py`
  (`Split`, `proof_tasks`, `criterion_files`, `task_files`, `find_splits`; `task_files` reads the log as `integrity.commits` and the
  files as `integrity.tagged_files`). Run: `tests/unit/verifier/test_judge_followup.py
  tests/unit/verifier/test_diffparts.py`.

- [x] 1.2 The groups and the bound. Tests first, same file: `test_files_are_taken_while_they_fit` (a file that does not
  fit is skipped and the next tried; the room is `MAX_PART_CHARS − parts.reserve`);
  `test_a_cut_or_unseen_file_is_never_shown` (SCN-VER-198: `data/seed.json` in a cut part and `src/app/seed.py`:
  `no_fit`, `not_shown` holds `("data/seed.json", 2, 300000)`; `a.py` 80000 and `b.py` 70000: `no_fit`);
  `test_criteria_share_a_group_when_their_files_fit` (SCN-VER-197 first case: groups `(C-1, C-2)` and `(C-3,)`);
  `test_the_calls_are_bounded_by_the_parts` (SCN-VER-197 second case: two groups, the third criterion's record has
  `outcome` `no_call_left`); `test_primary_files_group_first_and_task_files_fill_the_rest` (C-1 and C-2 whose primary files fit together but whose secondary files do not: one group; the secondary files of C-1 never take the room of C-2's primary files; a secondary file that does not fit is skipped and listed in `not_shown`);
  `test_a_groups_files_are_in_part_order` (the shown entries in part order, then the packing's order); `test_the_same_input_gives_the_same_groups` (two runs equal). Code:
  `src/l4/verifier/judge_followup.py` (`Group`, `plan_followups`). Run: that file.

- [x] 1.3 Applying a follow-up and the note. Tests first, same file: `test_a_follow_up_replaces_only_its_criteria`
  (SCN-VER-201: C-1 `pass`, C-2 keeps `insufficient_evidence`, C-9 keeps the part's `pass`; the order of `criteria`
  is the merged one); `test_a_follow_up_changes_only_its_own_group` (SCN-VER-201 second case: a follow-up for C-1 alone whose reply marks a test inadequate with an empty criterion and a test of C-2 inadequate, and a finding with an empty criterion: none is in the merged result, C-2's verdict and adequacy are the parts'; an entry for C-1 stays);
  `test_adequacy_and_findings_merge_as_a_parts` (a test of the group's criterion that the follow-up calls inadequate with a reason of its own is inadequate; a finding of the same severity, criterion and title is listed once; feedback,
  accepted, satisfied and assumptions are the merged ones); `test_the_note_of_each_outcome` (D8 word for word for
  `answered` with and without not-shown files (three named, then `+N more`), `not_answered`, `no_answer`
  (`schema_invalid`, `limit`), `no_fit`, `no_call_left`; `parts` `(1, 2)` gives `1 and 2` and `(1, 2, 4)` gives `1, 2
  and 4`; None gives `""`). Code: `src/l4/verifier/judge_followup.py` (`apply_followups`, `split_note`). Run: that
  file and `tests/unit/verifier/test_judge_parts_merge.py`.

## 2. The prompts (design D5, D6; L4-VER-056, L4-VER-057)

- [ ] 2.1 Tests first, new `tests/unit/verifier/test_judge_followup_prompt.py`:
  `test_the_part_prompt_has_the_rule_of_a_criterion_shown_in_part` (SCN-VER-194: the D6 rule word for word, after the
  rule of a criterion not in the part); `test_the_follow_up_prompt` (SCN-VER-194: headed `## Diff (base...head),
  follow-up 1 of 1`; the D5 rules word for word with `judged in 2 parts` and `their files lie in parts 1 and 2`; the file list names every file of the diff: `shown: src/app/export.py (part 1, 60000 characters)` and `not shown: data/seed.json (part 2, 300000 characters)`, shown files first, capped at 200 lines with `+K more files: see verification.md`; no line says "all" or "together" of the shown files, and the rules say the prompt shows some of the change's files; the criteria
  block holds only the group's ids; with feedback, accepted, satisfied and tasks given to the round, the follow-up
  prompt has none of their blocks and `accepted_ids`, `feedback_ids` and `satisfied_ids` are empty);
  `test_part_and_followup_are_exclusive` (`ValueError` when both are given); `test_the_template_is_judge_12`
  (`PROMPT_VERSION == 12`, `prompt.version == "judge@12"`). Where `verifier-cap` has not already done it, change the `judge@11` literals to `judge@12` and the `PROMPT_VERSION == 11` asserts to `12` in `tests/unit/verifier/test_prompt.py` (`:46`, `:59`, `:107`),
  `test_judge_satisfied.py:64` (both), `test_judge_feedback.py` (`:105`, `:162`), `test_judge_step.py:286`,
  `test_judge_accepted.py:85` (both) and `test_judge_sources.py` (`:77`, `:102`); nothing else in them (the comment
  at `test_prompt.py:148` and `SINGLE_SHA` stay).
  `test_a_diff_within_the_cap_keeps_its_prompt_byte_for_byte` (the user text equals `SINGLE_USER`; this change does not touch `SINGLE_SHA`: `verifier-cap`, implemented first, changes `SYSTEM` and regenerates it) and
  `test_review_m2_a_part_that_shows_the_code_judges_it_and_no_rule_sends_a_test_elsewhere` must pass unchanged. Code:
  `src/l4/verifier/judge.py` (`FollowUpView` with `files`, `_followup_rules`, `_followup_listing`, `build_judge_prompt(...,
  followup=None)`, the D6 line in `_part_rules`, `PROMPT_VERSION = 12` with its comment line: `verifier-cap` already sets 12, so keep the number and add the comment),
  `src/l4/templates.lock.json` (regenerated with `.venv/bin/python -m l4.templatelock --write` after this task; the judge's `version` is 12 already and this change does not change `SYSTEM`, so the lock may be unchanged). Run: `tests/unit/verifier/test_judge_followup_prompt.py tests/unit/verifier/test_prompt.py
  tests/unit/verifier/test_judge_satisfied.py tests/unit/verifier/test_judge_feedback.py
  tests/unit/verifier/test_judge_accepted.py tests/unit/verifier/test_judge_sources.py
  tests/unit/test_template_lock.py`.

## 3. The judge step (design D4, D5, D7, D8; L4-VER-057, L4-VER-058)

- [ ] 3.1 The follow-up calls. Tests first, new `tests/unit/verifier/test_judge_step_followup.py` (the `parts_bench` world with a trace of dotted pytest ids such as `tests.test_report::test_header`, `task.red_ok` events with `criteria`, and commits per task; the file sizes of SCN-VER-190 scaled to the lowered `cap`):
  `test_a_split_criterion_is_passed_by_one_follow_up` (SCN-VER-190: three calls; the third prompt is follow-up 1 of 1
  with the three files and C-1 only; `run.judged` has C-1 `pass`; `result.judge_calls == 3`);
  `test_a_criterion_in_one_part_gets_no_follow_up` (SCN-VER-191: two calls, then a one-part diff: one call);
  `test_an_uncovered_held_inadequate_or_decided_criterion_gets_no_follow_up` (SCN-VER-192: uncovered, held, a person's verdict, and a criterion whose only passing tracing test the parts called inadequate);
  `test_a_follow_up_for_one_criterion_leaves_the_others_alone` (SCN-VER-201: a reply that marks a test of another criterion inadequate changes nothing outside its group);
  `test_a_fail_or_not_verifiable_of_a_part_is_not_rejudged` (SCN-VER-196);
  `test_two_groups_make_two_calls_and_the_bound_holds` (SCN-VER-197);
  `test_a_follow_up_with_no_usable_answer_keeps_the_round` (SCN-VER-199: a reply that breaks the schema twice, then a
  `RoleLimit` with no next judge: `run.judged` is the merged verdict, no `the judge's reply was discarded` hold, no
  `RoleUnavailable`, `judge_split` C-1 `no_answer` with `schema_invalid`, then `limit`);
  `test_a_follow_up_fail_goes_through_the_counterexample_rule` (SCN-VER-200: `result.cx_runs` has C-1 `unexecuted`);
  `test_the_follow_up_records` (SCN-VER-202: `result.judge_followups` row, `result.judge_split`, `verify.judge` with
  `followup`, `followups`, `criteria` and no `part`; `prompt_sha256` over the three hashes; `judge_reply` the parts' worst; `judge_profile`, `judge_model` and `independence` of the round the parts' judge even when the follow-up ran on a fallback profile; `cost_usd` adds the follow-up's cost). The tests of `tests/unit/verifier/test_judge_step.py` must pass with
  their call counts unchanged. Code: `src/l4/verifier/ladder.py` (`_judge_step`: after `merge_part_verdicts`,
  `find_splits`, `plan_followups`, one `build_judge_prompt(..., followup=…)` and `_ask_judges(...)` per group, a
  `RoleLimit` or a reply without a verdict kept as `no_answer`, then `apply_followups`; `run.judged` and
  `result.judge_verdict` set from the verdict after `apply_followups`; `result.judge_reply` set back to
  the parts' worst; the `verify.judge` keys through `_ask_judges(..., followup=(k, m, ids))`),
  `src/l4/verifier/types.py` (`judge_followups`, `judge_split`). Run: `tests/unit/verifier/test_judge_step_followup.py
  tests/unit/verifier/test_judge_step.py tests/unit/verifier/test_judge_chain.py
  tests/unit/verifier/test_judge_reply_ledger.py`.

- [ ] 3.2 The note, the report, a resumed round. Tests first: `tests/unit/verifier/test_aggregate.py`:
  `test_the_split_note_ends_a_reason_that_rests_on_the_judge` (`pass`, judge `fail` without a reproduced
  counterexample, `insufficient_evidence` and `not_verifiable` end with `; <note>`; a failing tracing test, a
  person's verdict, uncovered and held do not; `split=""` gives today's reasons byte for byte).
  `tests/unit/verifier/test_judge_step_followup.py`: `test_the_question_says_the_evidence_was_split` (SCN-VER-195:
  the `Why:` line of C-1's question word for word); `test_verification_md_lists_the_follow_ups` (SCN-VER-202:
  `judged in 2 parts and 1 follow-up` and the row word for word; `follow-ups` for two);
  `test_a_resumed_round_keeps_the_notes` (SCN-VER-203: `verdict.json` holds `judge_followups` and `judge_split`;
  the evidence of the next round reads them; no judge call; the same reason; and, with a follow-up `pass` for C-1
  and an uncovered C-2, `judge_verdict` holds C-1 `pass` and the resumed round keeps C-1 `pass`). Code:
  `src/l4/verifier/aggregate.py`
  (`aggregate_criterion(..., split="")`), `src/l4/verifier/ladder.py` (`_finalize` passes
  `split_note(result.judge_split.get(c.id))`), `src/l4/verifier/report.py` (the judge line, the follow-up rows, the
  two keys of `verdict.json`), `src/l4/verifier/evidence.py` (the two keys copied beside `judge_parts`). Run:
  `tests/unit/verifier/test_aggregate.py tests/unit/verifier/test_aggregate_rows.py
  tests/unit/verifier/test_judge_step_followup.py tests/unit/verifier/test_verdicts.py tests/unit/verifier`.

## 4. Docs, SPEC, CHANGELOG (design D9)

- [ ] 4.1 Tests first, new `tests/unit/docs/test_judge_parts_docs.py`:
  `test_the_spec_has_the_requirements_and_scenarios` (`**L4-VER-056 `, `**L4-VER-057 `, `**L4-VER-058 ` in order after
  `**L4-VER-047 `; `#### SCN-VER-190 ` to `#### SCN-VER-203 ` in order after `#### SCN-VER-157 ` and before `## MODIFIED
  Requirements`; `` `judge-parts` `` in the change table; L4-VER-018 says `judge@12`; the step 9 row names
  `L4-VER-056 to L4-VER-058`); `test_the_runbook_names_a_split_criterion` (§7.1 names `its evidence was split over parts`, `follow-up
  call` and `Files by part`); `test_the_skill_names_a_split_criterion` (`operate.md`'s verdict questions name `its
  evidence was split over parts`); `test_the_changelog_names_the_follow_up` (in `## 0.4.21 (unreleased)`, above `##
  0.4.20 (`: `follow-up`, `L4-VER-056`, `judge@12`, `its evidence was split over parts`).
  `tests/unit/docs/test_plan_run_lessons_docs.py` must pass unchanged. Code: `CHANGELOG.md` (the lines below, under `##
  0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)`; when another branch has added the heading first, merge the lists
  under the same subheadings), `docs/runbook.md` (§7.1, after the `judge view: …` bullet: a criterion question whose
  `Why:` says `its evidence was split over parts …` means the diff was judged in parts and this criterion's files lay in
  several; the text says whether a follow-up call judged them together and what it answered; read the files in
  `verification.md` under `Files by part` and answer as for any criterion), `plugins/l4/skills/l4/references/operate.md`
  (the same in one bullet under **Verdict questions**). The SPEC text is already in this branch; change it only to match
  the code, with the orchestrator. Run: `tests/unit/docs tests/unit/skills`, `scripts/check_spec.py docs/SPEC.md`,
  `openspec validate judge-parts --strict`.

- [ ] 4.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract`,
  `.venv/bin/ruff check src tests scripts plugins`, `.venv/bin/ruff format --check` on every changed file, and
  `.venv/bin/mypy` on the changed src files. Done when all pass and `git status` is clean.

## CHANGELOG lines (`## 0.4.21 (unreleased)`; task 4.1 writes them as they stand)

### Changed
- A diff judged in parts no longer asks a person about a criterion only because its code lay in two parts
  (L4-VER-056, L4-VER-057). When the parts' merged verdict for a covered criterion is `insufficient_evidence` and its
  files (its tracing tests, the code they import, the files of its tasks' commits and the files the parts cited) lie
  in two or more parts, the judge step makes a follow-up call that shows those files together, whole, within one
  part's characters, and its verdict replaces `insufficient_evidence`. Split criteria share a call when their files
  fit together; a round makes at most as many follow-up calls as parts. A criterion any part failed, passed or
  called `not_verifiable` is never judged again, and a follow-up with no usable answer keeps the parts' verdict.
- Each part prompt asks a part that shows only some of a criterion's code to cite the files it holds. The judge
  template is `judge@12`.

### Fixed
- The question about such a criterion says what happened (L4-VER-058): its `Why:` line and `verification.md` end with
  `its evidence was split over parts 1 and 2 of the diff: …` and what the follow-up call answered, or why none was
  made. Before, the reason was only `the judge answered insufficient_evidence`, the same as for a criterion with no
  evidence. `verification.md` lists each follow-up call; `verdict.json` records `judge_followups` and `judge_split`.
