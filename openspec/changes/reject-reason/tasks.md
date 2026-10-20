Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every rule, text and signature is in `design.md` (D1 to D4
  and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree (`reject-reason`), with its own `.venv`. Never change git configuration. Never
  push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `reject-reason <n.m>: …`, with no
  trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- Name a consumer repository only as "a consumer". Put no consumer's command, file or requirement text into a test,
  a fixture or a doc: the examples below are abstract on purpose. Put no local path in docs or fixtures.
- One implementer does the tasks in order, on top of the previous commits.

Test worlds: `tests/unit/verifier/test_fixunit.py` (`criterion`, `FAMILY`, `result`, `reject`, `det`; a finding
rejected through `l4.verifier.verdicts.apply_finding_verdicts`, as `test_the_human_s_decision_survives_a_long_finding_
detail_in_the_fix_task` does); `tests/unit/specs/test_kiro_fix_unit.py` (`parent`, `provider_of`);
`tests/unit/specs/test_fix_unit.py` (`parent`, `provider_of`, `FixCli`); `tests/unit/verifier/test_ladder_fix.py`
(`run_l4`, `judge`, `KNOWN`, `UNKNOWN`, `red_known_only`, `green_step`, `pinning_red`, `edit_questions_on_origin`,
`FIX_DIR`, `Run.pushed`, `Run.events`, `Run.adapter.requests`); `tests/unit/verifier/test_hold_verdicts.py`
(`_question_text`, the `raise_verdict_questions` call with a `Sink` and `Redactor({})`).

The abstract example of the tests (SCN-VER-205): criterion `C-00000001` of `FAMILY`; a judge finding `Finding(
Severity.MAJOR, "Unknown id exits 2, not 1", "the criterion requires exit 1; the code exits 2", "judge", "C-00000001",
spec_gap=True, suggested_fix="WHEN the id is unknown THEN the command exits 2")`; the person's reason `the criterion
requires exit 1; the code exits 2` as `Q-002`.

## 1. The planner (design D1, D2; L4-VER-059)

- [x] 1.1 Tests first, in `tests/unit/verifier/test_fixunit.py`:
  `test_a_reason_without_a_scenario_does_not_pin_the_judges_suggestion` (SCN-VER-205: one group, `criteria ==
  ("C-00000001",)`, not a chore, `plan.delta is None`, `plan.consumed == ["Q-002"]`, the detail starts `Decided by human
  in Q-002: the criterion requires exit 1; the code exits 2.`, and `"exits 2" not in repr(plan.delta)` and `"the
  command exits 2" not in repr(plan)`; fails today: the delta pins the suggestion);
  `test_a_bare_reject_of_a_finding_that_is_not_a_spec_gap_is_checked_against_its_criterion` (D1: the finding of the
  abstract example with `spec_gap=False`, reason `""`: the detail starts `Decided by human in Q-002: rejected, no
  reason given.`, `plan.delta is None`, one group); `test_a_bare_reject_of_a_spec_gap_is_not_converted` (SCN-VER-215,
  D1a: the abstract example, reason `""` or blank: `plan.groups == []`, `plan.consumed == []`, `rejected with no reason:
  answer again with a reason or a scenario` and the finding's id in `plan.not_converted[0]`; with the criterion also
  rejected with a reason, the task is made and both decisions are quoted);
  `test_a_reason_that_quotes_a_scenario_and_gives_its_own_pins_the_last` (SCN-VER-216: `when_then` of `the scenario
  says WHEN a THEN b, but it is wrong. WHEN c THEN d` is `- **WHEN** c\n- **THEN** d`; a text with one `WHEN … THEN …`
  gives what it gave, `WHEN a WHEN b THEN c` has the `when` `b`, a reason with a lone `WHEN` after its scenario still
  gives the first scenario; `ends_with_scenario` agrees);
  `test_the_persons_scenario_is_the_check` (SCN-VER-207: reason `the criterion requires exit 1. WHEN the id is unknown
  THEN the command exits 1`: one ADDED scenario `- **WHEN** the id is unknown\n- **THEN** the command exits 1` under
  `Greet — regression 1`, and `"the command exits 2"` is in no scenario; passes today, it guards the rule);
  `test_a_criterion_reject_is_quoted_and_its_scenario_pinned` (SCN-VER-208: the finding rejected as `Q-003` with `the
  code exits 2`, the criterion as `Q-002` with `the criterion requires exit 1. WHEN the id is unknown THEN the command
  exits 1`: one group, the detail starts `Decided by human in Q-003: the code exits 2; Q-002: the criterion requires
  exit 1.`, `plan.consumed == ["Q-003", "Q-002"]`, and the one scenario is Q-002's; fails today: Q-002's reason is
  missing and the suggestion is pinned);
  `test_both_scenarios_of_a_finding_and_its_criterion_are_pinned_the_findings_first` (two different `WHEN … THEN …`:
  two scenarios in that order, both with the finding's id);
  `test_the_same_reason_in_two_answers_gives_two_decisions` (the same short reason as Q-003 and Q-002: the detail has
  `Q-003: <reason>` and `Q-002: <reason>`, each whole; the decisions share the budget of `_fit_detail`, so do not
  assert a total length);
  `test_a_rejected_spec_gap_with_no_criterion_and_no_scenario_is_not_converted` (SCN-VER-209: the finding with
  criterion `None` and `suggested_fix="WHEN a THEN b"`, rejected `wrong`: `plan.groups == []`, `plan.consumed == []`,
  and `answer again with a scenario` and the finding's id in `plan.not_converted[0]`; fails today: the suggestion made
  a task);
  `test_an_unrejected_minor_spec_gap_still_pins_the_judges_suggestion` (SCN-VER-210: `Verdict.PASS`, `fix_minor=True`,
  no human verdict, a minor spec gap with `WHEN a blank code is given THEN it raises ValueError`: that scenario is
  pinned).
  The escalation of SCN-VER-215 and SCN-VER-209 through `decide_fix`: in `tests/unit/verifier/test_ladder_fix.py`,
  `test_a_hand_edited_bare_reject_of_a_spec_gap_escalates_with_no_convertible_finding` (the first-round world of task
  1.3 with the finding tied to `KNOWN` and the answer written by `edit_questions_on_origin` as `reject`: the second run
  has no `fix.spawned`, exits 13, and the last `phase.changed` has `reason == "no_convertible_finding"`), and
  `test_a_rejected_spec_gap_with_no_criterion_and_no_scenario_escalates_with_no_convertible_finding` (SCN-VER-209: the
  finding tied to no criterion, the answer `reject: wrong`; the same assertions).
  Every existing test of the file must pass unchanged (the prototype of D1 passed 178 tests of `test_fixunit.py`,
  `test_ladder_fix.py`, `test_legacy_round.py`, `test_hold_verdicts.py`, `test_verdicts.py`, the fix unit writers and
  `test_decided_tests_chore.py`). Code: `src/l4/verifier/fixunit.py` (`_verdicts_of`; a spec gap whose verdicts all have an empty reason is not
  converted; `WHEN_THEN` in `verdicts.py` takes the last scenario; in `_candidates`, the verdicts,
  the scenarios from them only, the judge's suggestion only without a verdict, every verdict's decision; the note
  stripped with the finding's own verdict; the module docstring's sentence on the source of a scenario).
  Run: `tests/unit/verifier/test_fixunit.py tests/unit/implementer/test_decided_tests_chore.py`.
  Result: test_fixunit.py 36 pass (14 new, the new tests failed before the code); fixunit.py `_verdicts_of`, the bare-reject skip, `WHEN_THEN` takes the last scenario.

- [x] 1.2 The fix unit files. Tests first:
  `tests/unit/specs/test_kiro_fix_unit.py`: `test_a_rejected_spec_gap_without_a_scenario_restates_only_its_criterion`
  (SCN-VER-205, Kiro: build the plan of 1.1's first test with the `parent` world's criterion, write it with
  `create_fix_unit`: `bugfix.md` has one `2.n` item (the criterion restated), the task's `_Requirements:_` line names
  only it, and no file of the folder contains `the command exits 2`).
  `tests/unit/specs/test_fix_unit.py`: `test_a_rejected_spec_gap_without_a_scenario_gets_skip_specs` (SCN-VER-205,
  OpenSpec: `.openspec.yaml` has `skip_specs: true`, no `specs/` folder, `proposal.md` has the decision before the
  judge's detail, and no file contains `the command exits 2`).
  No code is expected beyond 1.1; a failure here is a gap in 1.1. Run: those two files.
  Result: both writer tests pass with no writer change.

- [x] 1.3 End to end. Test first, in `tests/unit/verifier/test_ladder_fix.py`:
  `test_a_rejected_spec_gap_without_a_scenario_is_fixed_against_its_criterion` (the world of
  `test_a_rejected_judge_finding_gets_a_fix_task_that_goes_red_then_green_and_round_3_passes`, with the finding tied to
  `KNOWN` and a suggested fix that pins the code as it is, `WHEN a lowercase code is given THEN it is rejected`; the
  person answers `reject: a lowercase code must be accepted`; then the second run: `fix.spawned` consumes `Q-001`,
  `{FIX_DIR}/.openspec.yaml` has `skip_specs: true`, `{FIX_DIR}/tasks.md` cites the finding and `KNOWN`, the
  suggestion's text is in no pushed file of `FIX_DIR`, and the `# Unit context` block of the first fix-unit red
  prompt in `adapter.requests` (the text from `# Unit context` to the next `# ` heading, `prompt.py:328`) holds
  `Decided by human in Q-001: a lowercase code must be accepted` and not `THEN it is rejected`; the check looks at that
  block only, not the whole prompt, which may carry the criteria's own text). Choose the red and
  green steps from the file's levers so that the unit reaches the fix unit's red; the test is about what the fix unit
  says, not about round 3. Run: that file.
  Result: three ladder tests pass (fixed against the criterion; a hand-edited bare reject and a no-criterion gap escalate with `no_convertible_finding`); the unit-context block is cut at the next `\n\n# `.

## 2. The questions (design D3; L4-VER-060)

- [x] 2.1 Tests first, in `tests/unit/verifier/test_hold_verdicts.py` (it has the `raise_verdict_questions` world;
  a new file `tests/unit/verifier/test_verdict_question_texts.py` is fine too):
  `test_a_finding_question_says_how_to_set_the_check` (SCN-VER-211: a judge-only major finding on a criterion of the
  round, not a spec gap: the file has `your reason comes first in it`, `Without one, the fix is checked against
  criterion <id> as it is written.`, `REJECT_OPTION`, and not `a reject does not use it`);
  `test_a_spec_gap_question_says_the_suggestion_is_the_code_as_it_is` (SCN-VER-212: the same finding with
  `spec_gap=True` and the suggested fix `WHEN the id is unknown THEN the command exits 2`: `SUGGESTION_IS_THE_CODE`
  follows the suggested fix; with an empty suggested fix, and with a suggested fix of advice, `Clarify in the spec
  whether an unknown id exits 1 or 2` (negative case: `ends_with_scenario` is false), the sentence is absent and the
  suggested fix is still shown);
  `test_a_finding_question_with_no_criterion_says_the_sentence_is_needed` (SCN-VER-213: `CHECK_WITHOUT_CRITERION`,
  and not `Without one, the fix is checked against`);
  `test_a_criterion_question_says_the_same_of_its_scenario` (SCN-VER-214: a `needs_human` outcome: `Without one, the
  fix is checked against the scenario above as it is written.`, `REJECT_OPTION`, and not `If the code is right and the
  scenarios are incomplete`).
  The existing `test_scn_ver_137_the_question_of_a_judge_view_hold_says_what_accept_and_reject_do` must pass unchanged:
  `_hold_question` keeps `("accept", "reject: <reason>")` (it asserts no `WHEN` in a judge-view hold's question; the
  prototype of D3 failed it when the hold's options changed too). Code: `src/l4/verifier/verdicts.py` (the constants of
  Contracts, `SPEC_GAP_NOTE` among them; `_finding_question` shows `SUGGESTION_IS_THE_CODE` only when
  `ends_with_scenario(finding.suggested_fix)`; `_criterion_question`). Run: `tests/unit/verifier/test_hold_verdicts.py
  tests/unit/verifier/test_verdicts.py tests/unit/verifier/test_supersede_verdicts.py
  tests/unit/verifier/test_verdict_reentry.py` and the new file.
  Result: new file `tests/unit/verifier/test_verdict_question_texts.py`, 5 tests pass; test_hold_verdicts.py, test_verdicts.py unchanged and green.

- [x] 2.2 The answer command refuses a bare reject of a spec gap (design D1a; L4-VER-060; SCN-VER-206). Tests first, in
  `tests/unit/specs/test_questions_cli.py` (use `questions_world.py`; build the verdict question with the real writer
  `l4.verifier.verdicts._finding_question`, so the test follows `SPEC_GAP_NOTE`):
  `test_a_bare_reject_of_a_spec_gap_question_is_refused` (`check_question` for `answer` with the text `reject`, then
  `reject:` and `reject.`: a `Refusal` with message `a spec gap's reject needs a reason or a WHEN ... THEN ...` and the
  fix `l4 questions answer Q-001 --unit <unit> --text "reject: <reason>[, then WHEN ... THEN ...]"`; through the
  command the exit is 2 and the file is unchanged);
  `test_a_reject_with_a_reason_of_a_spec_gap_question_is_accepted` (`reject: the criterion requires exit 1`, and
  `reject WHEN a THEN b`);
  `test_a_bare_reject_of_other_verdict_questions_is_accepted` (a finding that is not a spec gap, a criterion question,
  a hold question; and `accept` of a spec gap);
  `test_the_replace_of_a_spec_gap_answer_by_a_bare_reject_is_refused` (`--replace` goes through the same check).
  Code: `src/l4/specs/questions_cli.py` (`check_question`, after the `_DECISION` check; import `parse_answer` and
  `SPEC_GAP_NOTE` from `l4.verifier.verdicts`). Run: `tests/unit/specs/test_questions_cli.py
  tests/unit/specs/test_questions.py tests/unit/specs/test_questions_agents.py`.
  Result: `bare_gap_reject` in questions_cli.py; 4 new tests (11 cases) in test_questions_cli.py; the file's 85 tests pass. A criterion question is not refused (design D1a).

## 3. Docs, SPEC, CHANGELOG (design D4)

- [x] 3.1 Tests first, new `tests/unit/docs/test_reject_reason_docs.py`:
  `test_the_spec_has_the_requirements_and_scenarios` (`**L4-VER-059 ` after `**L4-VER-006` and before `**L4-VER-007`;
  `**L4-VER-060 ` before `**L4-VER-014 `; `#### SCN-VER-205 ` to `#### SCN-VER-216 ` in order, after `#### SCN-VER-157 `
  and before `### 23.9.1`; the L4-VER-006 text has `when L4-VER-059 gives it one` and `a spec gap that L4-VER-059
  gives no scenario adds none`; a change-table row with ``| `reject-reason` |``, matched by name, not number);
  `test_the_runbook_says_what_a_reject_without_a_scenario_does` (the "For verdict questions" section has `checked
  against`, `suggested fix` and `describes what the code does now`);
  `test_the_skill_says_it_too` (`plugins/l4/skills/l4/references/operate.md`, "Verdict questions": `checked against`
  and `suggested fix`);
  `test_the_way_out_of_no_convertible_finding_names_a_replaced_reject` (the runbook's section `#### 7.3.1 ` and the
  skill's `no_convertible_finding` bullet each have `--replace` together with `WHEN … THEN …`);
  `test_the_changelog_names_the_fix` (in `## 0.4.21 (unreleased)`, above `## 0.4.20 (`: `L4-VER-059`, `L4-VER-060`,
  `answer again with a scenario`, `suggested fix`).
  Code: `CHANGELOG.md` (the lines below, under `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)`; another
  0.4.21 change may add the same heading: whoever merges second keeps one heading and merges the lists under the same
  subheadings), `docs/runbook.md` (section "For verdict questions", the `WHEN … THEN …` bullet: add `Without one, the
  fix is checked against the criterion as it is written (the question's own criterion, or the one the finding cites);
  a finding with no criterion needs the sentence. The judge's suggested fix is not used for a reject: for a spec gap it
  describes what the code does now. To pin it, end your reason with it. When you reject both a criterion and a finding
  about it, both reasons go into the fix unit, and the WHEN … THEN … of either is pinned.`),
  `plugins/l4/skills/l4/references/operate.md` (the `reject` bullet of "Verdict questions": add `Without one, the fix
  is checked against the criterion as it is written; the judge's suggested fix is never used for a reject (for a spec
  gap it describes what the code does now): to pin it, end your reason with it.`), the runbook's section 7.3.1 (step 5:
  a reject listed `answer again with a scenario` is replaced the same way, with `--text "reject: <reason>. WHEN …
  THEN …" --replace`, then the retry of step 3) and the skill's `no_convertible_finding` bullet (the same in one
  sentence; both also say that a spec gap's bare `reject` is refused by the command and what to add). The SPEC text is
  already in this branch; change it only to match the code, with the orchestrator. Run: `tests/unit/docs tests/unit/skills`,
  `scripts/check_spec.py docs/SPEC.md`, `openspec validate reject-reason --strict`.
  Result: tests/unit/docs/test_reject_reason_docs.py 5 pass; check_spec.py clean; openspec validate --strict valid.

- [ ] 3.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract`,
  `.venv/bin/ruff check src tests scripts plugins`, `.venv/bin/ruff format --check` on every changed file, and
  `.venv/bin/mypy` on the changed src files. Done when all pass, `git status` is clean, and `git grep -n
  "when_then(f.suggested_fix)" -- src` finds one line, inside the branch for a finding with no verdict.

## CHANGELOG lines (`## 0.4.21 (unreleased)`; task 3.1 writes them as they stand)

### Changed
- A rejected spec-gap finding whose criterion the unit does not have, answered without a `WHEN … THEN …`, is listed as
  not converted (`answer again with a scenario`) instead of becoming a task from the judge's suggested fix
  (L4-VER-059). When no other finding converts, the unit escalates with `no finding of this round can be converted into
  a fix task`; replace the answer with one that ends with a scenario (`l4 questions answer … --replace`), or give the
  fix as a behaviour feedback item, then `l4 retry`.
- Verdict questions say how to set the check a fix must pass: end the reason with `WHEN … THEN …`; without one the fix
  is checked against the criterion as it is written; for a spec gap, the suggested fix describes what the code does now
  and a reject does not use it (L4-VER-060).
- `l4 questions answer` refuses a `reject` with no reason on a spec gap's question (exit 2): add a reason, or a `WHEN …
  THEN …` (L4-VER-060). A reason alone is accepted: the fix is checked against the cited criterion and the red step
  writes a failing test for the reason, and the gap may be asked again, since no scenario is added. A bare reject of a
  spec gap that reached the file by hand is not converted either (`rejected with no reason`, L4-VER-059).
- A reason's scenario is its last `WHEN … THEN …`: a reason may quote the criterion's and then give its own.

### Fixed
- A fix task no longer pins the judge's suggested fix when a person rejected the finding without a `WHEN … THEN …` of
  their own (L4-VER-059). For a spec gap the judge writes its suggestion as the behaviour the code shows now, so a reject
  such as "the criterion requires exit 1; the code exits 2" made a fix unit whose added scenario said exit 2 next to
  the criterion that says exit 1, and the task could not pass both. The task now cites the criterion and is checked
  against its scenarios; only a person's `WHEN … THEN …` adds a scenario. A spec gap that no person rejected (a minor
  with `verifier.fix_minor_findings`) still pins the suggestion.
- A fix task quotes every reject it consumes. When a person rejected both a finding and its criterion, the criterion's
  reason and its `WHEN … THEN …` were consumed but appeared nowhere in the fix unit (L4-VER-059).

## 4. Integration (after the parallel changes merge; not done in this change's branch)

- [ ] 4.1 (integration, after verifier-cap): add the decision rule of `single.md:6` ("the person's decision is binding
  …") to `red.md` and `green.md` in the 0.4.21 bump. `verifier-cap` bumps `red.md` to v12 in the same release: take one
  version bump for both, and the four prompt-version test files that pin the template versions.
