## 1. One parser and the new question (L4-IMP-004)

- [ ] 1.1 Write the tests first, in `tests/unit/specs/test_questions.py` (or the module that tests `QuestionsFile`).
  Then add `edit_option`, `option_suggestion` and `accept_text` to `l4.specs.questions`, as design D1 and D2 say.
  `edit_option` cases:
  - the backticked form, which is returned unchanged;
  - the bare form `Edit src/x.test.ts: change` → ``Edit `src/x.test.ts`: change``;
  - a bare token without `/` or `.` → None;
  - a colon in the path → None;
  - no text after `: ` → None;
  - leading or trailing spaces on the option;
  - `Edit ./x.py: y`.

  `option_suggestion` cases: an open technical question with no block; one with a written block, `(empty)` included
  (None); a product question (None); an answered question (None); an option 1 that is no edit (None).
- [ ] 1.2 Write the tests first, in `tests/unit/implementer/` beside the existing `_suggest_edits` and `_with_note`
  tests (grep `_EDIT_OPTION`). Then replace `_EDIT_OPTION` in `l4.implementer.loop` with `edit_option`. The suggestion
  is the normalised text (SCN-IMP-418, SCN-IMP-419).

## 2. A question already open (L4-QMD-008, L4-DLG-014)

- [ ] 2.1 Write the tests first, then `QuestionsFile.with_option_suggestion(qid, *, redactor)` (design D2), with a
  byte-level test: the block is added before `### Answer`, CRLF and the BOM are kept, and every other question is
  unchanged.
- [ ] 2.2 Write the tests first, in the tests of `l4 questions` (grep `run_show` and `build_edit` under
  `tests/unit/specs/`):
  - `build_edit("accept", …)` on a question with a bare option 1 and no block writes the block and Status `accepted`;
  - `effective_answer` of the read-back question is the normalised text, `is_answered` is true, and `answer_sha256`
    equals the sha256 of that text (SCN-QMD-29);
  - a written block is taken as it is and never replaced (SCN-QMD-30);
  - `answer` writes no block;
  - `show` text and JSON (`accept.from`), and the agent rule (`agent_refusal` reads the derived text);
  - `suggestion_effects` names the frozen path.

  Then `check_question`, `build_edit`, `run_show`, `agent_refusal` and `suggestion_effects` read `accept_text`. Use the
  question's exact shape from SCN-QMD-29: Kind technical, Status open, a harness note in Context, option 1 bare,
  option 2 another edit, an empty Answer block, no suggestion block.
- [ ] 2.3 Write the tests first, in the delegate tests (grep `check_reply` and `_answer` under `tests/unit/delegate/`):
  - `check_reply` keeps an `accept` of such a question with `unfreeze=True` when the path is a frozen test file;
  - it escalates when the path is a support file, or when `fix_task` is set;
  - the delegate pass writes the block and records `question.answered{by: delegate}` with the digest of the read-back
    question (SCN-DLG-122);
  - the prompt shows the derived suggestion under `Clarifier suggestion`;
  - the prompt's rules hold the new sentence (design D5).

  Then `check_reply` reads `accept_text`, and the delegate builds its prompt view with
  `suggestion_text=accept_text(question)`. Do NOT change `_file` or `QuestionsFile.load` (design D2).

## 3. Checks

- [ ] 3.1 Run `tests/unit/specs`, `tests/unit/implementer`, `tests/unit/delegate` and `tests/unit/clarifier` once, with
  pytest, never in a loop, and wait for them to finish. Run ruff check and ruff format on the changed files.

## 4. Docs (one pass at the end of the release)

- [ ] 4.1 Amend L4-IMP-004 (the sentence on option 1) and L4-QMD-008 (the added span and its read-back), and add the
  prompt sentence to L4-DLG-014. Add SCN-IMP-418 and SCN-IMP-419 after SCN-IMP-417, SCN-QMD-29 and SCN-QMD-30 after
  SCN-QMD-28, and SCN-DLG-122 after SCN-DLG-121. Add change-table row 85 `unfreeze-option-form`, and a CHANGELOG 0.4.39
  entry under Fixed.
