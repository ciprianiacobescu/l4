Read `design.md` first (D1-D9). Requirements: L4-VER-083, L4-VER-084 and L4-VER-085 (`docs/SPEC.md`), scenarios
SCN-VER-331..342, 350 and 352. Run single test files only (`uv run --frozen pytest <file> -x -q`), never a whole directory, never two
runs at once, and never a wait loop on `pgrep`. Secrets in tests: use a token shape the redactor knows (`"glpat-" +
"A1b2C3d4E5f6G7h8I9j0"`, as `tests/unit/implementer/test_excerpt_redaction.py` does); build a private-key block from
parts so that no test file holds a key marker as one string.

## 1. Step 5 keeps the failure and a bounded copy of the code (L4-VER-083, D1, D2)

- [x] 1.1 Write the tests first:
  - in `tests/unit/implementer/test_excerpt.py`: the redact-then-cut helper of D1 redacts a token that straddles the
    limit (no part of 8 characters or more is left), cuts at the last line end before the limit, cuts a single longer
    line at the limit, and leaves a text under the limit as the redactor gives it;
  - in `tests/unit/verifier/test_generate.py` (follow its fakes for `run_e2e` and the writer): a head run whose report
    fails the generated test with a body that holds `>` and `E` lines under an absolute worktree path gives an outcome
    `fails_at_head` whose `excerpt` holds those lines with the path relative and whose `code` is the bounded copy; the
    file written to the tree is the raw code; an outcome whose last written test did not fail at the head has `excerpt
    == ""`; with two attempts (first `fails_at_head`, then `lint_failed`) the outcome's code is the second reply's and
    its excerpt is empty; with a first `fails_at_head` and a second attempt that gives no code (a writer error) the
    outcome is `writer_failed` and keeps the first test's code and excerpt together (SCN-VER-350);
  - in `tests/unit/verifier/test_report_m15.py`: `verdict_json` writes `generated[].excerpt` when it is set and no key
    when it is empty; `code` is the bounded copy; a token that straddles 4,000 characters of the raw code is not in
    the written `verdict.json` in part (SCN-VER-332 for this file);
  - in `tests/unit/verifier/test_resume.py`: `restore_round` keeps `excerpt`, and a 0.4.59 record (no `excerpt`)
    restores with `""` and its stored code (SCN-VER-333).
  Run each file and see the new tests fail.
- [x] 1.2 Then add the helper to `src/l4/implementer/excerpt.py` (reuse `_redact_keys` and `_cut_at_line`), `excerpt`
  to `_Verdict` and to `GeneratedOutcome` (last field), the `failure_excerpt` call in the `fails_at_head` branch of
  `_discriminates`, and the bounded code and the excerpt in the `outcome` closure of `generate_ui_test`
  (`src/l4/verifier/generate.py`); `_generated_json` keeps or drops `excerpt` (`src/l4/verifier/report.py`). Define
  `MAX_CODE_CHARS` once. Run the files of 1.1, then `tests/unit/verifier/test_generate_support.py` and
  `tests/unit/verifier/test_integrity_generated.py`, one at a time.

## 2. The hold's question and the report (L4-VER-083, D3, D4)

- [x] 2.1 Write the tests first:
  - in `tests/unit/verifier/test_hold_verdicts.py`: SCN-VER-331 (`raise_verdict_questions(..., holds=[ui_hold_text(C)],
    generated=[<fails_at_head outcome with excerpt and code>])`: the section's `### Harness notes` holds the excerpt's
    lines and the code numbered, line 19 as `  19  ...`; the title and the `question.raised` event's `target` and
    `text_sha256` are those of the same call without excerpt and code; the Context ends with the sentence of D3);
    SCN-VER-334 (a code with the lines of the scenario: `QuestionsFile.load` finds one question with its usual
    subsections, no line of the file starts with a backslash, `unescape_text(notes_text)` equals the notes); SCN-VER-335
    (`not_testable` on the first reply, a `writer_failed` with no code, a restored outcome with neither: no notes, the
    Context is byte for byte that of 0.4.59); a token in the code or the excerpt does not reach `questions.md`
    (SCN-VER-332); SCN-VER-350 (a `writer_failed` outcome that keeps the code and the excerpt of an earlier attempt:
    both in the notes, and the code's heading names `writer_failed`);
  - in `tests/unit/verifier/test_report_m15.py`: the section `## Generated UI tests that were not accepted` with the
    item line and the six-space block (SCN-VER-333); no section when every outcome is accepted, waived or has no code
    (SCN-VER-335); a token is not in `verification.md` (SCN-VER-332);
  - in `tests/unit/delegate/` (the file that tests `QuestionView` or the delegate's prompt): the delegate's prompt for a
    UI hold question holds the notes' excerpt line.
  Run each file and see the new tests fail.
- [x] 2.2 Then add `_ui_hold_notes` and the sentence to `_ui_hold_lines`, and pass `notes=` from `_hold_question`
  (`src/l4/verifier/verdicts.py`); add the section to `render_verification_md` (`src/l4/verifier/report.py`). Run the
  files of 2.1, then `tests/unit/verifier/test_ui_flow.py`, `tests/unit/verifier/test_hold_binding.py` and
  `tests/unit/specs/test_questions.py`, one at a time.

## 3. The writer's retry (L4-VER-084, D5)

- [x] 3.1 Write the tests first in `tests/unit/verifier/test_generate.py`: SCN-VER-336 (the second request's prompt,
  read from the fake writer, holds `the test fails at the head:`, `Why it failed at the head:` and the excerpt's line
  inside the retry reason data block); SCN-VER-337 (a `non_discriminating` first attempt: the retry reason is the
  reason alone; a second test that passes at the merge base after a `fails_at_head` first attempt ends
  `non_discriminating`). Run and see them fail.
- [x] 3.2 Then change the retry reason in `generate_ui_test`. No template file, no `templates.lock.json` change. Run
  `tests/unit/verifier/test_generate.py` and `tests/unit/verifier/test_testwriter.py` (if present), one at a time.

## 4. One behaviour, one fix task (L4-VER-085, D8)

- [x] 4.1 Write the tests first:
  - in `tests/unit/verifier/test_hold_verdicts.py`: `settle_holds` with a rejected UI hold gives a finding with
    `criterion == C` and the id, title, detail, severity and source of 0.4.59, for a reason with and without a
    `WHEN … THEN …`; `is_ui_hold_finding` is true for it and false for a rejected scope, coverage or judge-view hold's
    finding and for a judge finding;
  - in `tests/unit/verifier/test_fixunit.py` (or a new `test_fixunit_ui_hold.py` next to it): SCN-VER-338 (one task,
    both finding ids, both decisions with the criterion's first, both questions in `consumed`, one `DeltaScenario`);
    SCN-VER-339 (two scenarios, one task); SCN-VER-340 (a family with two requirements: the scenario is under
    `<requirement> — regression 1`, its name is the criterion's scenario, no requirement title holds `— finding H-`);
    SCN-VER-341 (not converted, not consumed); a UI hold whose criterion is not in the family plans as in 0.4.59;
  - in `tests/unit/specs/test_kiro_fix_unit.py`: the plan of SCN-VER-338 gives one `2.n` item;
  - in `tests/unit/verifier/test_ladder_hold_fix.py`: SCN-VER-342 with a stored NEEDS_HUMAN round and two rejects (the
    verdict is FAIL, the fix unit has one task).
  Run each file and see the new tests fail.
- [x] 4.2 Then set the criterion in `_hold_finding` and add `is_ui_hold_finding` (`src/l4/verifier/verdicts.py`), and
  change `cited`, the sort, the skip and the scenario's name in `_candidates` (`src/l4/verifier/fixunit.py`). Run the
  files of 4.1, then `tests/unit/verifier/test_fixunit_reject_text.py`, `tests/unit/verifier/test_fixunit_finding_home.py`,
  `tests/unit/verifier/test_fixunit_test_only.py`, `tests/unit/verifier/test_fixunit_one_failure.py` and
  `tests/unit/specs/test_fix_unit.py`, one at a time.

## 5. Checks

- [x] 5.1 `docs/SPEC.md` holds L4-VER-083..085, SCN-VER-331..342, 350 and 352, change-table row 137 and the amendments to L4-VER-006,
  L4-VER-067 and the step-5 row of 10.2. Check them against the code and tell the orchestrator where they differ; do
  not edit `docs/SPEC.md`, `CHANGELOG.md`, `docs/runbook.md` or the skill. Run `uv run --frozen python
  scripts/check_spec.py docs/SPEC.md`.
- [x] 5.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
