Read `design.md` first (D1-D8). Requirements: L4-VER-078 and L4-IMP-102 (`docs/SPEC.md`), scenarios SCN-VER-308..310
and SCN-IMP-557..561. Run single test files only (`uv run --frozen pytest <file> -q`), never a whole directory, never
two runs at once, and never a wait loop on `pgrep`. Secrets in tests: use a token shape the redactor knows
(`"glpat-" + "A1b2C3d4E5f6G7h8I9j0"`, as `tests/unit/implementer/test_excerpt_redaction.py` does); build a private-key
block from parts (`"-----BEGIN " + "RSA PRIVATE " + "KEY" + "-----"`) so the test file never holds a key marker.

## 1. The round records an excerpt (L4-VER-078, D1)

- [x] 1.1 Write the tests first:
  - in `tests/unit/implementer/test_excerpt.py`: `case_excerpt(TestCase(..., detail=<a pytest body with an absolute
    worktree path, a `>` line and `E` lines>), worktree=..., tmp_root=None, redact=Redactor({}).redact_text)` holds the
    `>` and `E` lines, the path relative, at most 8 lines and 600 characters; a 2,000-character `E` line is cut at 600; a
    case with a message and no detail gives the message's first lines; a case with neither gives `""`; a body with the
    token gives no part of it (for each prefix of 8 characters or more, as `test_excerpt_redaction.py` checks); a body
    whose private-key block ends past the eighth line gives no line of the block;
  - in `tests/unit/verifier/test_failures_map.py`: SCN-VER-308 (`failure_records(unit, e2e, redact, excerpt=...)`: the
    record has `excerpt` and its old keys unchanged; without `excerpt=` the records are exactly as before); SCN-VER-310
    (30 failing unit tests, 2 browser tests: 20 + 2 records hold `excerpt`); a collection record gets the `E` lines of its
    detail through `collection_excerpt`; `verdict_json` writes `excerpt`, and `restore_round` keeps it (extend
    `test_a_reused_round_keeps_the_failures_and_an_old_one_has_none`).
  Run both files and see the new tests fail.
- [x] 1.2 Then add `MAX_RECORD_EXCERPT_CHARS = 600` and `case_excerpt` to `src/l4/implementer/excerpt.py` (reuse
  `_test_lines` and `_clean`; never name it `test_...`), the keywords `excerpt` and `collection_excerpt` and
  `MAX_EXCERPT_RECORDS = 20` to `failure_records` (`src/l4/verifier/gates.py`), and pass both from `tests()` in
  `src/l4/verifier/ladder.py` (`worktree=wb.worktree`, `tmp_root=wb.unit_cache / "gate-tmp"`,
  `redact=wb.redactor.redact_text`; the collection one: `error_lines` from `l4.gates.collection`, `_clean`, the
  redactor). Run the two test files, `tests/unit/implementer/test_excerpt_redaction.py`, `tests/unit/verifier/test_ui_flow.py`
  and `tests/unit/verifier/test_repair_integrity.py`, one at a time.

## 2. The fix unit's files (L4-IMP-102, D2, D3, D4)

- [x] 2.1 Write the tests first:
  - in a new `tests/unit/verifier/test_failures_block.py`: `shown_failure_ids` for each title of D2 (a gate finding takes
    every record of its gate, collection records included; `new tests failed` the named ids, also from a cut list; any
    other title none); `failure_block` formats `<id> (<kind>, <gate>):` and the excerpt lines indented by two spaces,
    falls back to `message`, keeps at most 8 tests and 6,000 characters with whole tests only and the `and <n> more`
    line, and gives `""` for ids with no record;
  - in `tests/unit/verifier/test_fixunit.py` (or a new `test_fixunit_failures.py` next to it): `plan_fix_unit` of a
    FAIL round with `e2e gate failed` and a `failures` map sets `Finding.failures` of that task; a feedback task and a
    task whose findings name no test have `""`; `redact_plan` redacts `failures` (a token in an excerpt is gone);
  - in `tests/unit/specs/test_fix_unit.py`: SCN-IMP-557 with the provider of that file (`create_fix_unit` with a
    `Finding(..., failures=<block>)`): `proposal.md` holds the lead line and the block on lines indented by four
    spaces under the finding's line, `tasks.md` is byte for byte what it is without `failures`, and the change
    validates (the tests there already run the pinned CLI or its stub: follow them);
  - in `tests/unit/specs/test_kiro_fix_unit.py`: the Kiro `design.md` holds the same lead line and indented block after
    the finding's detail, and `tasks.md` is unchanged.
  Run the files and see the new tests fail.
- [x] 2.2 Then add `shown_failure_ids`, `failure_block`, `MAX_SHOWN_FAILURES = 8` and `MAX_FAILURE_BLOCK_CHARS = 6000`
  to `src/l4/verifier/failures.py` (no harness import); `failures: str = ""` as the last field of `Finding`
  (`src/l4/specs/base.py`); in `src/l4/verifier/fixunit.py`, `_Candidate.failing: set[str]` filled in `_candidates`
  from `shown_failure_ids(result.failures, f.title, f.detail)` for every finding it groups, `Finding(...,
  failures=failure_block(result.failures, sorted(cand.failing)))` for every non-feedback group (the repair chore
  included), and `failures=redact(g.failures)` in `redact_plan`; the block in `_proposal` (`src/l4/specs/openspec.py`)
  and `_fix_design` (`src/l4/specs/kiro.py`) as D4 says. Run the files of 2.1, then `tests/unit/verifier/test_fixunit_repair.py`,
  `tests/unit/verifier/test_fixunit_one_failure.py`, `tests/unit/verifier/test_fixunit_feedback.py` and
  `tests/unit/specs/test_fix_unit_test_only.py`, one at a time.

## 3. The fix chore's prompt (D5)

- [x] 3.1 Write the tests first in a new `tests/unit/implementer/test_fix_failure_excerpt.py`, with the bench and
  `seed_round` of `tests/unit/implementer/test_fix_chore_e2e.py` (import them, or copy them): a stored round whose
  `failures` record of `TEST_X` has `"excerpt": "E       assert 1508 == 1500"`; `run_single(bench.wb, TASK,
  [E2E_FINDING], attempt=1)` with a blocked step (no e2e stub is reached): the first prompt
  (`bench.adapter.requests[0].prompt`) holds `# Failures of this task's tests` and `assert 1508 == 1500`
  (SCN-IMP-558; set the profile's `context_budget_tokens` low, or monkeypatch the planner, so that `proposal.md` is cut
  and the block is still there); with no `fix.spawned` (`seed_round(spawned=False)`) and with `failures=None` the
  prompt holds no such block (SCN-IMP-561); a `repair` chore's prompt holds none. Run and see them fail.
- [x] 3.2 Then add `PromptContext.failing_tests` and the block in `render_prompt` (`src/l4/implementer/prompt.py`,
  role `single`, not a repair), `fix_failure_text(wb, findings)` in `src/l4/implementer/tdd.py` (`_parent_verdict`, D2,
  D3), and thread `failing` through `run_single` (kind `fix`) -> `step_or_replay` -> `agent_step` -> `_prompt`. No
  template file changes. Run the new file, `tests/unit/implementer/test_fix_chore_e2e.py`,
  `tests/unit/implementer/test_single_phase.py` and `tests/unit/implementer/test_prompt.py`, one at a time.

## 4. The questions (D6)

- [x] 4.1 Write the tests first in `test_fix_failure_excerpt.py`:
  - SCN-IMP-559: as `test_a_chore_question_cannot_unfreeze_a_file` in `tests/unit/implementer/test_loop.py` does
    (monkeypatch `loop.chore_findings`), with a stored round as in 3.1: `questions.md` holds the agent's context, then
    `Harness note: the verifier recorded these failures for the tests of this task's findings:` and the excerpt line,
    and the Context still ends with the fix chore's note (`test_a_chore_question_cannot_unfreeze_a_file` and SCN-IMP-398
    keep passing);
  - SCN-IMP-560: `run_task` with a red step, a green step that fails the test gate (a red test still failing) and a
    green step that reports blocked with a question: the Context holds `Harness note: the previous attempt of this task
    was rejected: red tests still failing:` and a line of the ledger excerpt, before green's unfreeze note when the
    question is technical; a question of a first attempt has no such
    note; the question of a hung frozen test (`test_a_frozen_test_that_hangs_raises_one_question_naming_its_file_at_once`)
    is unchanged;
  - a token in the excerpt does not reach `questions.md`.
  Run and see them fail.
- [x] 4.2 Then add `notes` to `_questions` and `_raise_blocked` (the notes go between the agent's text and the note
  `_with_note` adds: give `_with_note` the joined text instead of `question.context`), and pass the two notes from
  `_run_task` (`src/l4/implementer/loop.py`) as D6 says. Run the new file, `tests/unit/implementer/test_loop.py`,
  `tests/unit/implementer/test_unasserted_clauses.py`, `tests/unit/implementer/test_suggested_edit.py` and
  `tests/unit/delegate/test_pass.py`, one at a time.

## 5. Checks

- [x] 5.1 `docs/SPEC.md` holds L4-VER-078, L4-IMP-102, SCN-VER-308..310, SCN-IMP-557..561 and change-table row 134.
  Check them against the code and tell the orchestrator where they differ; do not edit `docs/SPEC.md`, `CHANGELOG.md`
  or `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [x] 5.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.

## 7. Review fixes (the orchestrator's review of 9b4ff383)

- [x] 7.1 The harness notes are their own `### Harness notes` subsection (`NewQuestion.notes`, `_render_section`,
  `_SUBHEADING`, `Question.notes_text`, `QuestionView.context`), so no `asked` text that decides an unfreeze holds them
  (`suggestion_effects`, `unfrozen`, `config_opened`, `existing_tests`). Tests first: `test_harness_notes.py`,
  `test_questions.py`, `test_fix_failure_excerpt.py`.
- [x] 7.2 The reason of the previous attempt is `redact(redact(failure)[:300])`; the excerpts remove a private-key block
  with one marker (`_redact_keys`); a collection excerpt is cut at 8 lines; the OpenSpec failure block is indented by
  six spaces. Tests first: `test_harness_notes.py`, `test_excerpt.py`, `test_fix_unit.py`.
- [x] 7.3 Pins of surviving mutants: the ladder passes `collection_excerpt=` (`test_ui_flow.py`), the inner redaction of
  `collection_case_excerpt`, the cut at 300, the forbidden-path and clause questions get the notes, only a fix chore's
  questions get the failure block.
- [x] 7.4 Surviving mutants recorded as equivalent or near-equivalent, not pinned (round 2):
  - F2 (`case_excerpt`: no `_redact_keys` after `_clean`): near-equivalent. The body is redacted whole before any line
    is dropped, and making a path relative does not build a secret the redactor matches; the second pass is defence in
    depth after the paths are rewritten.
  - F3 (`case_excerpt`: the outer `lines[:MAX_TEST_LINES]` -> `MAX_TEST_LINES + 1`, `excerpt.py` line 172): equivalent.
    Every list that reaches it is already at most 8 lines (`_test_lines` ends with `out[:MAX_TEST_LINES]`, the other
    branches slice `[:MAX_TEST_LINES]` or `[:2]`).
  - F20 (the fix chore's question notes also for a `repair` chore, `loop.py` `== "fix"`): near-equivalent (inferred, not
    proved). A repair chore's step (`_run_repair`) ends in a held question or a rejected attempt, which carry the failure
    of its recorded tests themselves; the block would repeat it.
