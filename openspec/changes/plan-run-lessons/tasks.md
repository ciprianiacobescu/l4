Every task follows these rules:
- Read `design.md` of this change first; it names every function, text and constant. Do not change a text it quotes.
- Write the named tests first and see them fail for the reason the lesson gives, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>` (`uv sync` once if `.venv`
  is missing). Then `.venv/bin/ruff check .`, `.venv/bin/ruff format --check` on the files that changed, and
  `.venv/bin/python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only. Name a consumer "a consumer repository".
- A test may lower `l4.verifier.diffparts.MAX_PART_CHARS` (and `MAX_JUDGE_PARTS`) with `monkeypatch` to keep its files
  small; the code reads both at call time, never as default arguments.

## 1. The judge's diff leaves out the bookkeeping (L4-VER-040)

- [x] 1.1 Tests, `tests/unit/verifier/test_judge_step.py`: extend `_diff_world` (or add `_channels_world`) with, in the
  unit folder and in `<unit>-fix-1`, `questions.md`, `feedback.md`, `verification.md`, `.l4/ledger/r1.jsonl` and
  `.l4/review-accepted.json`, plus the project files `src/app/report.py`, `tests/test_report.py` and
  `docs/questions.md`. SCN-VER-130: `ladder._git_diff(wb, base, head)` holds the three project files and no file of
  the two unit folders, and its length flag is computed on that text. New file `tests/unit/verifier/test_diffparts.py`:
  `bookkeeping_pathspecs(["u", "u-fix-1"])` equals `[":(glob,exclude)**/.l4/**",
  ":(glob,exclude).serena/memories/harness/**", ":(literal,exclude)u/verification.md", ":(literal,exclude)u/questions.md",
  ":(literal,exclude)u/feedback.md", …the same three for u-fix-1]` in the order of `l4.state.review.UNIT_CHANNELS`.
  The existing tests `test_the_judge_diff_has_no_verification_md_of_the_family` and
  `test_a_project_verification_md_elsewhere_stays_in_the_diff` must still pass.
- [x] 1.2 Code: `src/l4/state/review.py`: `UNIT_CHANNELS = _NOT_SPEC` (public name, the tuple unchanged). New module
  `src/l4/verifier/diffparts.py` with `BOOKKEEPING_GLOBS` and `bookkeeping_pathspecs` (design D1). `ladder._git_diff`
  passes `"--", ".", *bookkeeping_pathspecs(_unit_dirs(wb))`; signature, cut and the S1 use stay.

## 2. The parts (L4-VER-041)

- [ ] 2.1 Tests, `tests/unit/verifier/test_diffparts.py`, pure and on a scratch git repository (`tmp_path`, `git init`,
  two commits): `group_key` on `src/app/report.py`, `tests/unit/test_report.py`, `pkg/report_test.go`,
  `web/report.test.ts`, `web/report.spec.ts`, `lib/report_tests.py` (all `report`) and `src/__init__.py` (`__init__`);
  `pack` fills parts in key order with whole entries (SCN-VER-131: `DiffEntry` texts of exactly the six lengths and
  paths of the scenario give the two parts it names, in that order, and a second `pack` of the same entries in another
  input order gives equal parts); an entry over `MAX_PART_CHARS` is a part of its own with `cut: True` and its text cut to
  `MAX_PART_CHARS` (SCN-VER-137, the part side); eleven entries of 70000 characters give eight parts and three
  `unseen` paths in pack order (SCN-VER-135, the packing side); `list_entries` lists a rename as one entry with both
  paths and its text shows `rename from`; `judge_parts` applies `bookkeeping_pathspecs`.
- [ ] 2.2 Code: in `src/l4/verifier/diffparts.py`: `MAX_PART_CHARS`, `MAX_JUDGE_PARTS`, `DiffEntry`, `DiffPart`,
  `DiffParts`, `group_key`, `pack`, `list_entries` (`git diff --name-status -z -M --no-color <base>...<head> -- .
  <pathspecs>`, then one `git diff --no-color --no-ext-diff --no-textconv -M <base>...<head> -- :(literal)<path>…` per
  entry, `Git.run_bytes`, decoded `utf-8`/`replace`), `judge_parts(git, base, head, unit_dirs)`. No unified-diff parsing.

## 3. One verdict from the parts (L4-VER-042)

- [ ] 3.1 Tests, new file `tests/unit/verifier/test_judge_parts_merge.py`, on `JudgeVerdict` objects built with
  `conftest.judge_reply`: SCN-VER-132 (C-1 `pass` in part 1, `insufficient_evidence` "not in this part" in part 2 →
  `pass` with part 1's evidence; FB-001 true in part 1, false "not in this part" in part 2 → addressed); SCN-VER-133
  (C-2 `pass` then `fail` with a counterexample → `fail` with part 2's counterexample; test T adequate in part 1,
  inadequate in part 2 → inadequate); SCN-VER-134 (FB-002 true, then false with `src/app/export.py:40 still writes the
  old header` → false with that evidence). Also: `not_verifiable` beats `insufficient_evidence`; findings repeated
  across parts appear once; `riskiest_assumptions` are three, taken in turn; `accepted` and `satisfied` follow the
  feedback rule; one reply comes back unchanged; a list every part left out stays `None`.
- [ ] 3.2 Code: new module `src/l4/verifier/judge_parts.py` with `merge_part_verdicts` (design D3);
  `NOT_IN_PART = "not in this part"` in `src/l4/verifier/judge.py`.

## 4. The part prompt (L4-VER-041)

- [ ] 4.1 Tests, `tests/unit/verifier/test_prompt.py`: with `part=PartView(2, 3, listing)` the user text has
  `## Diff (base...head), part 2 of 3`, the three rules with `not in this part` outside every `<l4:data>` block, a
  `<l4:data kind="diff parts">` block that lists every file with its part and its length, and only the given diff;
  with `part=None` the user text for the arguments of this file's `build()` is the same string as before the change
  (run the builder once before editing `judge.py` and keep its output in the test as a literal); `SYSTEM` is
  unchanged; `prompt.version == "judge@10"`.
- [ ] 4.2 Code: `src/l4/verifier/judge.py`: `PartView`, `build_judge_prompt(..., part: PartView | None = None)`,
  `PROMPT_VERSION = 10` with the comment `10: the diff in parts`.

## 5. The judge step in parts (L4-VER-041, L4-VER-042, L4-VER-043)

- [ ] 5.1 Tests, `tests/unit/verifier/test_judge_step.py`, with the `judge_unit`-style bench, `Scripted` holding one
  reply per part, and a lowered `MAX_PART_CHARS`: SCN-VER-131 (two parts: two judge calls, each user message holds
  `part K of 2` and the whole file list, two `verify.judge` events with `part` 1 and 2 and `parts` 2, no hold that
  starts with `judge view:` or `the diff is longer`, `result.judge_parts` has two rows, `result.prompt_sha256` is the
  sha256 of the two part hashes joined with `\n`, and `verification.md` says `judged in 2 parts`); SCN-VER-135 (eleven
  files over eight parts: eight calls, the hold `judge view: the diff needs more than 8 parts of <cap> characters: the
  judge did not see …` naming the three unseen files); SCN-VER-136 (part 2 answers `schema_invalid` twice: the hold
  `the judge's reply was discarded (part 2 of 2, schema_invalid: …)`, `run.judged is None`, no criterion verdict
  recorded); SCN-VER-137 (one file over the cap: the hold ``judge view: the diff of `uv.lock` is longer than one part
  (<cap> characters): the judge saw only its start``). A diff within the cap is one call with no part heading.
- [ ] 5.2 Code: `src/l4/verifier/ladder.py`: `_judge_step` per design D4 and D5 (the two `judge view:` holds made from
  `DiffParts`; the old hold line removed); `_ask_judges(vc, prompt, result, *, part: tuple[int, int] | None = None)`
  adds `part`/`parts` to `verify.judge`; `src/l4/verifier/types.py`: `VerifyResult.judge_parts: list[dict[str, Any]]`
  (default empty); `src/l4/verifier/report.py`: `judge_parts` in `verdict.json`, `, judged in N parts` on the judge
  line and one line per part in `verification.md`. `_s1_step` is not touched.

## 6. Holds on the judge's view (L4-VER-043, L4-VER-044)

- [ ] 6.1 Tests, `tests/unit/verifier/test_hold_verdicts.py`. First move the tests that use `LONG_DIFF` to test the
  `other` kind to `NOT_MEASURED` (an `other` hold): `test_a_rejected_hold_of_another_kind_with_a_scenario_becomes_a_fix_task`
  (with a scenario reason about coverage), `test_a_rejected_hold_of_another_kind_without_a_scenario_still_escalates`,
  and the parametrize of `test_the_question_of_any_other_hold_asks_for_a_scenario_and_promises_nothing` (drop
  `LONG_DIFF`). Then new tests: SCN-VER-137 (`hold_kind` is `judge_view` for both `judge view:` texts; their question
  says `accept` means a person checked the files, says `A fix unit cannot shrink the diff`, and holds no `WHEN`);
  SCN-VER-138 (a rejected `judge view:` hold whose reason ends with `WHEN the diff is long THEN the judge SHALL see
  every file`: `settle_holds` gives one `human` major finding titled `Rejected hold: the judge could not see all of the
  diff`; `plan_fix_unit` makes no group and lists it in `not_converted`; `fixloop._no_task_cause([finding])` is
  `("a person rejected a hold on the judge's view of the diff: a fix unit cannot shrink the diff",
  "judge_view_rejected")`, and for a finding of another title it is today's `no_convertible_finding` pair);
  SCN-VER-139 (the same with `LONG_DIFF`, the 0.4.14 text: `hold_kind` is `judge_view`, no task). The tests that use
  `LONG_DIFF` with a reason that has no scenario (SCN-VER-66 and the ones after it) must pass unchanged.
- [ ] 6.2 Code: `src/l4/verifier/verdicts.py`: `HoldKind` with `judge_view`, `LEGACY_LENGTH_HOLD`,
  `JUDGE_VIEW_PREFIX = "judge view: "`, `JUDGE_VIEW_REJECTED_TITLE`, `hold_kind`, `hold_subjects`, `_hold_question`,
  `_hold_finding` (design D5); `src/l4/verifier/fixunit.py`: `_candidates` skips a finding with that title before the
  scenario logic and records its question in `unconverted`; `src/l4/verifier/fixloop.py`: pure
  `_no_task_cause(findings) -> tuple[str, str]` used by `decide_fix` where it chose `no_convertible_finding`.
- [ ] 6.3 Tests for the way out (SCN-VER-138, the person's side): `tests/unit/state/test_next_step.py` (an escalated
  unit with `halt_reason="judge_view_rejected"`: `next_step` names `l4 restart --unit`, `--replace` and
  `l4 retry --unit`, and not `l4 feedback add`; `way_out(unit, "no_convertible_finding")` is `feedback_way_out(unit)`;
  `way_out(unit, "fix_rounds_exhausted")` is `None`); `tests/unit/state/test_spec_edited.py` (`_refuse_stopped` of such
  a unit: its `exit_reason` names the same and not `l4 feedback add`); `tests/unit/ci/test_resume_label.py` (the
  escalated section with `reason_code="judge_view_rejected"` is `### Escalated: …` and `To go on: <judge_view_way_out>.`).
- [ ] 6.4 Code: `src/l4/state/next_step.py`: `JUDGE_VIEW_REJECTED`, `judge_view_way_out`, `way_out` (design D6), used
  by `next_step`; `src/l4/orchestrator.py` (`_refuse_stopped`) and `src/l4/ci/resume_label.py` (the escalated section)
  call `way_out` instead of testing `NO_CONVERTIBLE_FINDING`; `fixloop.py` imports `JUDGE_VIEW_REJECTED`.

## 7. A limit of an active plan, by a person (L4-YOLO-050, L4-YOLO-051)

- [ ] 7.1 Tests: `tests/unit/yolo/test_yolo_state_fold.py`, SCN-YOLO-135 (active, waiting with
  `unit_awaiting_human`, stopped with `merge_refused` and one stale merge, each then `plan.extended{extend: {runs: 5}}`:
  status, `wait_reason`, `stop_reason` and `stale_merges` unchanged, `extended.runs == 5`; `plan.extended` before
  `plan.activated` changes nothing); `tests/unit/yolo/test_yolo_state_limits.py`, SCN-YOLO-131 (`max_runs` 90,
  `plan.extended{extend: {runs: 20}}`, a charge of 90 runs: `reached` is None, and `effective_limits(...).runs == 110`).
- [ ] 7.2 Code: `src/l4/yolo/state.py`: `plan.extended` in `fold_plan` (design D7) and a line about it in the module
  docstring.
- [ ] 7.3 Tests, `tests/unit/yolo/test_yolo_commands_manage.py`. First add
  `monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)` to every existing test that passes an
  `--extend-…` and expects it to work or to reach a limit message (`test_a_cost_limit_needs_more_money`,
  `test_an_extension_that_does_not_clear_the_usage_is_refused`, `test_the_runs_limit`,
  `test_the_attempts_limit_of_the_stopped_unit`, `test_the_deadline`, and in
  `tests/unit/yolo/test_yolo_commands_final_review.py` the test that runs `--extend-attempts 1`); keep
  `test_resume_of_an_active_plan_is_refused` (its text is the prefix of the new refusal). Then, each new test of a
  person with `_stdin_tty` patched to True: SCN-YOLO-130 (plan with
  `max_runs` 90 and 82 runs charged, a person: exit 0, the last event is `plan.extended` with `actor == "person"`,
  `extend == {"runs": 20}`, `limits_before["runs"] == 90`, `limits_after["runs"] == 110`; the fold says `active`; no
  `plan.resumed`; `forge.called("start_run") == []`; the output has `runs 90 -> 110` and `nothing resumed and no run
  started`); SCN-YOLO-132 (no `--extend-…`: exit 2, the four option names, `world.kinds()` unchanged);
  SCN-YOLO-133 (no `max_runs`: `has no run limit`; a deadline 2026-10-20T18:00:00Z and `--extend-deadline
  2026-10-20T12:00:00Z`: `is not later than the deadline in force`; nothing written); SCN-YOLO-134 (`CLAUDECODE=1` in the
  world's environment, `p1` seeded active, then a fresh world with `p1` seeded stopped with `limit_runs`: exit 2, `raising a plan's limits is a
  person's decision`, a `Fix:` line with `l4 yolo resume p1 --reason`, nothing written); SCN-YOLO-136 (after the
  extension `l4 yolo status p1` shows `runs 82 of 110`, `extended: runs 90 -> 110 by`, `(person): three units left`,
  and the `Next:` line names `l4 yolo resume p1 --reason TEXT --extend-runs N`; `--json` has `extensions`).
- [ ] 7.4 Code: `src/l4/yolo/commands.py`: `run_resume` (the active-plan path, the no-op refusals and the output of
  design D7; the person check of D8 after `_extend` and before `store.read()`), `_describe` (`extensions`), `_render`
  (the `extended:` lines), `_next_line` (the active text of D7); `src/l4/cli.py`: the help of `yolo resume` becomes
  `Resume a stopped or waiting delivery plan once the cause is gone, or raise a limit of an active one (--extend-…).`

## 8. After an answer (L4-YOLO-052, L4-YOLO-053)

- [ ] 8.1 Tests. `tests/unit/yolo/test_yolo_cycle_planner.py` (or a new `test_yolo_cycle_still_waits.py`), with
  `yolo_cycle_world`'s `snapshot`: `still_waits` is true for `awaiting_human` with an open question, false once
  `l4.planner.answers_unblock` is patched to return `("Q-001",)` (as `test_yolo_cycle_integration.py` does), false for
  `implementing`; `commands.answered_units([...])` holds exactly the `awaiting_human`/`clarifying` units for which
  `still_waits` is false. The whole of `tests/unit/yolo/test_yolo_cycle_*.py` passes unchanged after the refactor.
  `tests/unit/yolo/test_yolo_commands_manage.py`, with a new helper `answered(monkeypatch, *units)` that wraps
  `commands._read_units` like `phases()` and adds the ids to `units.answered`: SCN-YOLO-137 (waiting
  `unit_awaiting_human`, phase `awaiting_human`, answered: exit 0, last event `plan.resumed`, a `start_run` call);
  SCN-YOLO-138 (not answered: exit 2, `openspec:add-b is still awaiting_human: answer its questions first
  (l4 questions --unit openspec:add-b)` and `continues by itself at the run that reads the answer`; nothing written);
  SCN-YOLO-139 (`l4 yolo status p1`, not answered: the `Next:` line has `l4 questions --unit openspec:add-b`,
  `l4 questions answer Q-NNN --unit openspec:add-b --text TEXT`, `continues by itself`, and no `l4 yolo resume`);
  SCN-YOLO-140 (answered: the `Next:` line has `the answers of openspec:add-b are pushed and the next run reads them`,
  `l4 yolo resume p1 --reason TEXT` and the `how_to_start` text of the world's forge). `test_resume_waits_for_the_questions`
  keeps passing.
- [ ] 8.2 Code: `src/l4/yolo/cycle.py`: `ACTIONABLE` and `still_waits` (design D9), used by `_live` and `_cause_gone`
  with no change of behaviour; `src/l4/yolo/commands.py`: `_Units.answered`, `answered_units(snapshots)`, filled in
  `_read_units`; `resume_blocker(..., answered=...)` and its refusal text; `run_resume` and `_describe` pass
  `units.answered`; `_next_line(..., unit_phase=..., answered=..., start=...)` with the two texts of design D10
  (`start` from `l4.state.retry.how_to_start(ctx.app, ctx.cfg, ctx.target)`).

## 9. Docs

- [ ] 9.1 `docs/SPEC.md`:
  - the nine requirements as Part I paragraphs in SPEC's form (`**L4-VER-040 <title>.** <text>`), with the text of this
    change's specs: L4-VER-040..044 after L4-VER-018, L4-YOLO-050..053 after L4-YOLO-035;
  - the scenarios in Part II, in SPEC's form (`#### SCN-VER-130 (+) <title> · L4-VER-040`, then `- **Given**`,
    `- **When**`, `- **Then**`), in id order: SCN-VER-130..139 after SCN-VER-77, SCN-YOLO-130..140 after SCN-YOLO-92.
    The `·` references: SCN-VER-130 L4-VER-040; SCN-VER-131 L4-VER-041, L4-VER-042; SCN-VER-132..134 L4-VER-042;
    SCN-VER-135 L4-VER-041, L4-VER-043; SCN-VER-136 L4-VER-042; SCN-VER-137 L4-VER-043; SCN-VER-138 L4-VER-044;
    SCN-VER-139 L4-VER-043, L4-VER-044; SCN-YOLO-130..133, 135, 136 L4-YOLO-050; SCN-YOLO-134 L4-YOLO-051;
    SCN-YOLO-137, 138 L4-YOLO-052; SCN-YOLO-139, 140 L4-YOLO-053;
  - §10.2, row 9: one sentence that a diff over 120000 characters is judged in parts (L4-VER-041) whose replies are
    merged (L4-VER-042), and that what the judge cannot see is a `judge_view` hold (L4-VER-043, L4-VER-044);
  - L4-VER-018: `The prompt template is judge@9` becomes `The prompt template was judge@9; it is judge@10 since
    L4-VER-041`;
  - L4-OPS-022: one sentence that an escalation with `judge_view_rejected` names its own way out (L4-VER-044);
  - L4-YOLO-013: after `l4 yolo resume MUST be refused while the cause is still there`, add `; an answer that is pushed
    and not yet read is no cause (L4-YOLO-052)`; L4-YOLO-014: `More allowance MUST be an explicit l4 yolo resume
    --extend-…, recorded` gains `(in plan.resumed from a stop or a wait, in plan.extended on an active plan, by a
    person: L4-YOLO-050, L4-YOLO-051)`;
  - §2.1, the row of `l4 yolo resume`: add `on an active plan, an --extend-… raises the limit and resumes nothing
    (plan.extended, L4-YOLO-050); an --extend-… is a person's (L4-YOLO-051)`, and `plan.extended` in its last column;
  - the change table: a new row after the last row present (row 40 when the last is 39 `capacity-loop`):
    `plan-run-lessons`, what it delivers in one sentence per lesson with the ids and
    `openspec/changes/plan-run-lessons/`, exit criteria `the consumer repository's next plan run: a unit over the cap
    judged in parts; a limit raised while the plan is active; a resume after an answer`.
  Then `.venv/bin/python scripts/check_spec.py docs/SPEC.md` reports no uncovered requirement and no undefined ref.
- [ ] 9.2 `docs/runbook.md`: §7.1 (the verdict-question bullet that names `the diff is longer than 120000 characters`
  as the example: the example goes, and a bullet says a `judge view:` hold is accepted when you checked the files it
  names, and a reject stops the unit: split the change; no `WHEN … THEN …` makes a fix unit of it); §7.3.1 (the example
  `the diff is longer than 120000 characters` goes); a new §7.3.2 "Escalated with judge_view_rejected" (cause, the two
  ways out with their commands); §12.3 (the NOTE "To give the plan more…": an active plan takes the same `--extend-…`
  before it stops, and only a person can give it); §12.4 (the `awaiting_human` row: answer with `l4 questions answer`,
  which starts a run; the plan continues by itself at that run; no resume is needed, and `l4 yolo resume` starts it at
  once once the answer is pushed). `docs/yolo-mode.md`: the Limits paragraph (an active plan, `plan.extended`, a
  person's), the Stops and waits paragraph (a plan that waits for an answer continues at the run that reads it), the
  row of `l4 yolo resume` in its command table. `plugins/l4/skills/l4/references/operate.md`: the `l4 yolo resume` line
  (an active plan's limit, a person only) and the verdict-question bullets (a `judge view:` hold: accept or split, never
  a scenario). `CHANGELOG.md`: a section `## 0.4.16 (unreleased)` at the top of the releases (create it when missing),
  with `### Fixed` (the parts and the bookkeeping list; the `judge_view` holds and `judge_view_rejected`; the resume and
  the hints after an answer) and `### Changed` (`l4 yolo resume --extend-…` on an active plan; an agent can no longer
  raise a plan's limits).
- [ ] 9.3 Run `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/verifier tests/unit/state tests/unit/ci
  tests/unit/yolo tests/unit/specs`, `.venv/bin/ruff check .`, `.venv/bin/python scripts/check_spec.py docs/SPEC.md` and
  `npx --yes @fission-ai/openspec@1.14.1 validate plan-run-lessons --strict`; all pass.
