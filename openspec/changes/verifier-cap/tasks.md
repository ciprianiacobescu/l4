Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first. Every text, field, signature and version is in `design.md`
  (D1 to D10 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>`, `.venv/bin/ruff format --check <changed files>` and
  `.venv/bin/mypy <changed src files>`. A task that edits `docs/SPEC.md` also runs
  `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must be clean.
- Work only in this branch's worktree (`verifier-cap`), with its own `.venv` (`uv sync --inexact`). Never change git
  configuration. Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `verifier-cap <n.m>: …`, with no
  trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.
- Name a consumer repository only as "a consumer". Put no local path in docs or fixtures, and no test name or path
  taken from a consumer's repository: the scenarios use generic ids (`t::flow`, `C-aaaaaaaa`).
- One implementer does the tasks in order, on top of the previous commits.

Test worlds: `tests/unit/verifier/test_traceability.py` (`crit`, `case`, `report`, `red_ok`, `proof`, `CFG`);
`tests/unit/verifier/test_aggregate.py`; `tests/unit/verifier/test_verdicts.py` (`crit`, `outcome`, `ask`);
`tests/unit/verifier/test_judge_step.py` (`judge_unit`, `make_bench`); `tests/unit/verifier/test_prompt.py` (the judge
prompt); `tests/unit/implementer/conftest.py` (`make_bench`, `Bench`, `red_step`, `result`, `KNOWN`, `STUB`);
`tests/unit/implementer/test_tdd_red.py`; `tests/unit/implementer/test_vacuity.py` (`staged`, the remedy tests at
`:166` and `:181`); `tests/unit/implementer/test_criterion_tests_chore.py` (a test chore);
`tests/unit/implementer/test_prompt.py` (`ctx`).

## 1. Step 4 keeps the candidates, and the record keeps them (design D4, D6; L4-VER-054)

- [x] 1.1 Tests first, new `tests/unit/verifier/test_traceability_cap.py`:
  `test_a_proved_passing_test_over_the_cap_is_a_candidate` (four criteria, `t::flow` traces all four with a red proof
  for each, cap 3: every criterion is `uncovered`, its `ignored` has `("t::flow", "it traces 4 criteria
  (verifier.max_criteria_per_test=3)")` as today, and its `capped` is one `TracingTest("t::flow", "passed",
  "zero_value", over_cap=4)`; a red record with `via: not_applicable` keeps its note on the candidate);
  `test_no_proof_or_skipped_is_no_candidate` (SCN-VER-182: no proof, or `skipped`, gives an empty `capped` and the same
  ignored reason); `test_a_failing_test_over_the_cap_is_no_candidate`;
  `test_the_record_keeps_the_candidates_and_the_notes` (SCN-VER-184, part: `dataclasses.asdict` of the evidence, then
  `evidence._evidence`, gives back `capped`, `over_cap` and `note`; a dict without `capped`, `over_cap` and `note` loads
  with `()`, `0` and `""`). The existing `tests/unit/verifier/test_traceability.py` must pass unchanged (`:193` keeps
  its reason). Code: `src/l4/verifier/types.py` (`TracingTest.over_cap`, `CriterionEvidence.capped`),
  `src/l4/verifier/traceability.py` (`trace_criteria` reads the proof before the cap and fills `capped`; the module
  docstring names L4-VER-054), `src/l4/verifier/evidence.py` (`_evidence`). Run: `tests/unit/verifier`.
  Done: `trace_criteria` reads the proof before the cap and keeps a proved, passing test over it in `capped` (`over_cap` = the unit's criteria it traces); `_evidence` reads `note`, `over_cap`, `capped`.

## 2. The judge sees the candidates and names them (design D4, D5, D6; L4-VER-054)

- [x] 2.1 Tests first, new `tests/unit/verifier/test_count_named.py`:
  `test_a_judge_named_test_over_the_cap_covers_its_criterion` (SCN-VER-178: 12 criteria, `t::flow` traces 5, judge pass
  and `test_adequacy` true: `covered`, the test in `tests` with its proof, `adequate` true and `over_cap` 5, gone from
  `ignored`); `test_a_test_cited_only_by_the_pass_does_not_count` (SCN-VER-179: an evidence item `{kind: test, ref:
  t::flow}` and no `test_adequacy` entry: `uncovered`; with the entry: `covered`);
  `test_a_test_over_the_ceiling_never_counts` (SCN-VER-180: 5 criteria and a test of all 5; 29 criteria and tests of
  15 and of 10, ceiling `min(14, 9) = 9`; the judge passes and names it for each: nothing moves; a test of 9 in 29
  moves); `test_the_judges_doubt_wins` (SCN-VER-181: `adequate:
  false` for the criterion, `adequate: false` with `criterion: ""`, and a `fail` verdict: nothing moves for those);
  `test_named_tests_reads_the_worst_verdict_and_the_adequacy_entries` (`named_tests` on a verdict that lists a criterion
  twice, pass and fail: it is not in `passed`; the pairs of rule 2 come from `test_adequacy` only, so an evidence item
  adds none; the pairs of rule 3); `test_a_part_that_never_saw_the_test_names_nothing` (SCN-VER-181, parts case: a
  merged reply whose entry has `reason: "not in this part"` and `adequate: true` after `judge_parts` gives no pair in
  `named`, and nothing is rescued through `count_named`). Code: `src/l4/verifier/traceability.py`
  (`count_named`, `OVER_CAP_LABEL`), `src/l4/verifier/judge.py` (`named_tests`). Run: that file and
  `tests/unit/verifier/test_traceability.py`.
  Done: `count_named(evidence, passed, named, rejected, cap=3)` (positional, so `*named_tests(verdict)` unpacks; `rescue_ceiling` = `min(M // 2, 3 * cap)`) and `judge.named_tests` (entries from `test_adequacy` only; `not in this part` entries ignored).

- [x] 2.2 Tests first: `tests/unit/verifier/test_prompt.py`: `test_the_matrix_lists_the_candidates` (SCN-VER-183: the
  line `C-aaaaaaaa  uncovered  no discriminating test; over the per-test cap: t::flow (traces 5 criteria)`; seven
  candidates list five and `(+2 more)`; the system text holds `over the per-test cap` and `true only when the test
  asserts the observable outcome this criterion describes`; the version is `judge@12`);
  `tests/unit/verifier/test_judge_step.py`: `test_the_judge_step_counts_a_named_test_over_the_cap` (the `judge_unit`
  world with a test over the cap and a judge reply that names it: the round's trace has it in `tests`, the verdict
  aggregates `pass`, and `verification.md` shows `over the per-test cap: traces 5 criteria, named by the judge`);
  `test_a_resumed_round_keeps_the_named_test` (SCN-VER-184: the stored round resumed at aggregation keeps the criterion
  covered and the label). Move the version pins from 11 to 12: `tests/unit/verifier/test_judge_accepted.py:85`,
  `test_judge_satisfied.py:64`, `test_judge_step.py:286`, `test_judge_feedback.py:105` and `:162`,
  `test_judge_sources.py:77` and `:102`, `test_prompt.py:46` (`PROMPT_VERSION == 11`), `:59` and `:107`. The prompt's
  hash covers the system text (`judge.py:531`), so `SINGLE_SHA` (`tests/unit/verifier/test_prompt.py:149`) moves too:
  set it to the new hash and say why in its comment (`:148`). Regenerate `src/l4/templates.lock.json` with
  `.venv/bin/python -m l4.templatelock --write` (the judge's version and system-text hash change) and run
  `tests/unit/test_template_lock.py`. Code: `src/l4/verifier/judge.py` (`SYSTEM`,
  `PROMPT_VERSION = 12` and its comment), `src/l4/verifier/ladder.py` (`_gate_summary`; `count_named(result.trace,
  *named_tests(verdict), cap=…)` right after `apply_adequacy`, before `inadequate_findings`), `src/l4/verifier/report.py` (the
  label in the tests cell). Run: `tests/unit/verifier`, `tests/unit/test_template_lock.py`.
  Done: `judge@12` (system rule + `Naming the test in the evidence of your pass is not enough`), the matrix line `; over the per-test cap: …`, `count_named` after `apply_adequacy`, the label in `verification.md`; pins and `SINGLE_SHA` moved; lock regenerated.

## 3. The question of a criterion that only the cap left uncovered (design D7; L4-VER-055)

- [x] 3.1 Tests first, new `tests/unit/verifier/test_aggregate_cap.py`:
  `test_the_reason_says_the_judge_passed_it_and_only_the_cap_left_it` (SCN-VER-185: the text word for word, with `; the
  judge did not confirm it for this criterion`); `test_a_candidate_over_the_ceiling_says_so` (SCN-VER-186: `; it traces more than 4 of the unit's 8 criteria, the most the judge can make count`); `test_more_candidates_name_the_one_with_fewest_criteria` (two candidates of 7
  and 5: names the 5 and `(+1 more)`); `test_a_criterion_the_judge_did_not_pass_keeps_todays_reason` (SCN-VER-187:
  `fail`, `insufficient_evidence`, no verdict, and a pass with no candidate all give `uncovered: no adequate
  discriminating test traces it`); `test_require_traceability_off_keeps_its_suffix`; `test_a_round_like_the_incident`
  (SCN-VER-188: 29 criteria built with `trace_criteria`, a judge verdict as the scenario says, `count_named`, then
  `aggregate_criterion` for each: 26 `pass`, 2 with the reason of L4-VER-055, 1 with today's).
  `tests/unit/verifier/test_verdicts.py`: `test_the_question_names_the_fix_for_the_cap` (the question's context holds
  the reason and `Fix: answer accept if t::missing checks this criterion as its scenario says; or reject: give it its own test of at most 3 ids (a reject fails the criterion and spends a fix round).` before the answer line; a
  question of today's reason has no `Fix:` line). The existing `tests/unit/verifier/test_aggregate.py` and
  `test_aggregate_rows.py` must pass unchanged. Code: `src/l4/verifier/aggregate.py` (`CAP_ONLY`, the reason,
  `aggregate_criterion(..., cap, unit_size)`), `src/l4/verifier/ladder.py` (`_finalize` passes
  `wb.cfg.verifier.max_criteria_per_test` and `len(criteria)`), `src/l4/verifier/verdicts.py` (`_criterion_question`).
  Run: `tests/unit/verifier`.
  Done: `CAP_ONLY`, `_cap_reason`, `aggregate_criterion(..., cap, unit_size)`; `_finalize` passes both; `_cap_fix` in `verdicts.py` reads the test and cap from the reason.

## 4. The implementer's prompt states the cap (design D1; L4-VER-052)

- [ ] 4.1 Tests first, new `tests/unit/implementer/test_prompt_cap.py`: `test_every_role_states_the_cap_with_its_value`
  (SCN-VER-170: red, green, single and single with `adds_tests` under `pytest` and under `npx vitest run`, with
  `max_criteria_per_test` 3 and 2: the contract sentence of D1 with the value; the red prompt's two sentences;
  no `{max_criteria}` left in any prompt); `test_the_templates_are_versioned` (`contract` 13, `red` 12,
  `single_tests` 5, `single` 3, `green` 5); `test_tdd_passes_the_configured_cap` (a `make_bench` with
  `verifier.max_criteria_per_test: 4`: the rendered red prompt says `at most 4 ids`). Move the version pins:
  `tests/unit/implementer/test_prompt.py:47`, `:49`, `:369`, `:370`; `test_prompt_context.py:156`;
  `test_prompt_output.py:40`; `test_single_phase.py:35`, `:204`, `:317`; `test_check_criteria.py:69`;
  `test_criterion_tests_chore.py:75`; `test_decided_tests_chore.py:62`; `test_suggested_edit.py:75`;
  `test_tdd_red.py:294` (`contract@12` to `contract@13`, `red@11` to `red@12`). Regenerate
  `src/l4/templates.lock.json` with `.venv/bin/python -m l4.templatelock --write` (`implementer/contract` and
  `implementer/red` change version and hash). Code:
  `src/l4/implementer/templates/contract.md` (v13), `src/l4/implementer/templates/red.md` (v12),
  `src/l4/implementer/prompt.py` (`PromptContext.max_criteria_per_test`, the `{max_criteria}` fill in `_contract` and
  the phase text), `src/l4/implementer/tdd.py` (`_prompt` sets it). Run: `tests/unit/implementer`,
  `tests/unit/test_template_lock.py`.

## 5. The red step and the test chore check the cap (design D2; L4-VER-052)

- [ ] 5.1 Tests first: new `tests/unit/implementer/test_over_cap.py`: `test_over_cap_text` (the D2 text word for word
  for one test of 5; three tests and `(+1 more)` for four; ids that are not the unit's do not count; a test of exactly
  the cap gives ""); `test_a_red_step_with_a_test_over_the_cap_fails_before_any_variant_run` (SCN-VER-171, the
  `make_bench` world: a red step whose new test traces 5 of the unit's criteria fails the attempt with the text, the
  worktree is clean, no `test-zero`, base or pre-satisfied gate ran, and the next attempt's prompt holds the text);
  `test_a_test_at_the_cap_passes_and_other_ids_do_not_count` (SCN-VER-172, also with the cap 5);
  `test_tests_written_before_the_step_are_not_checked` (SCN-VER-174); `test_one_configured_cap` (SCN-VER-189: cap 4, a
  test of 4 passes and a test of 5 fails). `tests/unit/implementer/test_criterion_tests_chore.py`:
  `test_a_chore_test_over_the_cap_fails_the_chore` (SCN-VER-173: no discrimination run, no `task.tests_added`). Code:
  `src/l4/implementer/result.py` (`over_cap_text`), `src/l4/implementer/tdd.py` (the red step right after
  `check_criteria`; the chore on `added`, before `_discriminating_tests`). Run: `tests/unit/implementer`.

## 6. The zero-answer remedy respects the cap (design D3; L4-VER-053)

- [ ] 6.1 Tests first, `tests/unit/implementer/test_vacuity.py`: `test_the_remedy_never_advises_a_full_test`
  (SCN-VER-175); `test_the_remedy_names_a_test_with_room_and_all_its_ids` (SCN-VER-176);
  `test_the_remedy_uses_the_gates_form` (SCN-VER-177); and a test of `tag_example` (pytest and name forms). The two
  existing remedy tests (`:166`, `:181`) keep their meaning; their expected example now lists the test's ids in full.
  Code: `src/l4/implementer/result.py` (`tag_example`), `src/l4/implementer/discrimination.py` (`Vacuity.traced`,
  `cap`, `test_command`; `_zero_answer_remedy`; `vacuity_check` fills them from `real`, the provider's criteria and
  `wb.cfg`). Run: `tests/unit/implementer`.

## 7. Docs, SPEC, CHANGELOG (design D8, D10)

- [ ] 7.1 Tests first, new `tests/unit/docs/test_verifier_cap_docs.py`:
  `test_the_spec_has_the_requirements_and_scenarios` (`**L4-VER-052 ` to `**L4-VER-055 ` in order after `**L4-VER-051
  `; `#### SCN-VER-170 ` to `#### SCN-VER-189 ` in order after `#### SCN-VER-157 `; the L4-VER-009 paragraph names
  L4-VER-054; the §3.2 comment of `max_criteria_per_test` names L4-VER-052; `| 59 | \`verifier-cap\` |`, or the row
  the merge gives it); `test_the_eval_framework_names_the_write_time_check` (row 15 names `L4-VER-052` and
  `L4-VER-054`); `test_the_changelog_names_the_cap` (in `## 0.4.21 (unreleased)`: `verifier.max_criteria_per_test`,
  `too many criteria on one test`, `named by the judge`, `judge@12`, `only the per-test cap left it uncovered`). Code:
  `CHANGELOG.md` (the lines below, under `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)`; a parallel change may
  add the same heading: whoever merges second keeps one heading and merges the lists under the same subheadings),
  `docs/eval-framework.md` (row 15: `A test that traces more than this is not evidence for any of them, unless the judge
  names it for a criterion and it traces at most `min(half of the unit's, 3 × the cap)` (L4-VER-054); the implementer is told the value and
  a red step that writes such a test fails (L4-VER-052)`), `docs/runbook.md` (the verdict questions of §7.1: one
  bullet after the `judge view: …` bullet, for a criterion question whose `Why:` is the reason of L4-VER-055 (harness
  0.4.21 and later). It says that the judge passed the criterion and that the only tests that trace it trace more
  criteria than `verifier.max_criteria_per_test`, so they are not evidence; that the person reads the test the
  question names and answers `accept` when it checks this criterion as its scenario says, else `reject`; and that a
  `reject` fails the criterion and starts a fix round, whose unit writes a test of this criterion with at most that many
  ids. `test_verifier_cap_docs.py` checks that the runbook holds `only the per-test cap left it uncovered`). The SPEC
  text is already in this branch; change it only to
  match the code, with the orchestrator. Run: `tests/unit/docs`, `scripts/check_spec.py docs/SPEC.md`, `openspec
  validate verifier-cap --strict`.

- [ ] 7.2 The whole run once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract`,
  `.venv/bin/ruff check src tests scripts plugins`, `.venv/bin/ruff format --check` on every changed file, and
  `.venv/bin/mypy` on the changed src files. Done when all pass, `git status` is clean, `git grep -n
  "contract@12\|red@11\|judge@11" -- tests src ':!tests/unit/docs/test_plan_run_lessons_docs.py'` finds no assert (that
  file checks the historical `judge@11` lines of SPEC and CHANGELOG, which stay; a comment that names an old version
  may stay), and `git grep -n "max_criteria" -- src/l4/implementer` finds the prompt and the red check.

## CHANGELOG lines (`## 0.4.21 (unreleased)`; task 7.1 writes them as they stand)

### Added
- The implementer's contract states `verifier.max_criteria_per_test` with its value (L4-VER-052): a test that traces
  more than that many of the unit's criteria counts for none of them, so give each test one behaviour and at most that
  many ids, and put a criterion that many tests touch only on the tests that assert it directly (`contract@13`,
  `red@12`).
- A passing test over the cap that has a proof for a criterion counts for it when the judge passed the criterion and
  named the test for it, and the test traces at most `min(M // 2, 3 × cap)` of the unit's criteria (L4-VER-054). The judge's matrix lists
  such tests (`judge@12`), and `verification.md` labels a counted one `over the per-test cap: traces N criteria, named
  by the judge`. A test that traces everything is still no evidence.

### Changed
- A red step whose new test traces more than `verifier.max_criteria_per_test` of the unit's criteria fails its attempt
  before the discrimination runs, with `too many criteria on one test: <test> traces N of this unit's criteria (…),
  more than verifier.max_criteria_per_test (3), so the verifier counts it for none of them: split it into tests that
  each assert one behaviour and carry at most 3 ids, …` (L4-VER-052). A test chore's added test is checked the same
  way. Before, such a test was written, frozen, and ignored at verification, so its criteria became questions for a
  person. Tests that existed before the step are not checked.
- The zero-answer advice of the red phase proposes a test only when it has room under the cap, shows its whole id list
  in the gate's own form, and otherwise says to write a new test (L4-VER-053).

### Fixed
- A criterion that the judge passed and that only the per-test cap left uncovered says so: its reason reads
  `uncovered: the judge passed it, and only the per-test cap left it uncovered: <test> traces N criteria, …`, and its
  question names the fix (`accept` if the test checks it, or `reject: give it its own test of at most N ids`) (L4-VER-055). Before, it read
  `uncovered: no adequate discriminating test traces it`.
- A round resumed at aggregation keeps its tests' labels (`not applicable: no project code`, `accepted by Q-NNN: …`):
  the stored trace's `note` was dropped when it was read back.
