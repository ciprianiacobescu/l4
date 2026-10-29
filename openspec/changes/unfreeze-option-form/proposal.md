# A suggested edit is taken whether or not its path has backticks, also for a question already open

## Why

A blocked green step on a frozen test asks one technical question whose first option is "Edit `<path>`: <the exact
change>". The harness writes that option as the question's suggested answer, so one `accepted` unfreezes exactly that
file (L4-IMP-004, L4-IMP-002). It recognises the option with `^Edit `[^`\s]+`: \S` (`implementer/loop.py`). The path
must therefore be in backticks.

A model that writes the path bare ("Edit src/x.test.ts: …") gets no suggestion [V, a consumer's delivery plan,
2026-10-28: one implementer profile wrote the bare form; another profile, asked the same question in the next run, wrote
backticks]. Then:

- `l4 questions accept` has nothing to take ("has no clarifier suggestion to accept");
- the harness note says "write an answer that names its path", but the delegate's answer that names a frozen path is
  refused, because only the clarifier suggestion may unfreeze (L4-DLG-014);
- so the question waits for a person, or for an answer that asks the implementer to raise it again, which costs a full
  implementer round.

The consumer did the second: a person-free answer to raise the question again. The next implementer raised it with
backticks, the delegate accepted the suggestion, and the unit went on one run later.

## What changes

- One pure function `edit_option(text)` in `l4.specs.questions` reads both forms, "Edit `<path>`: <change>" and
  "Edit <path>: <change>". The path is one token with no whitespace, backtick or colon, and holds a `/` or a `.`. The
  function returns the backticked form, or None.
- A new question: `_suggest_edits` and the harness note use `edit_option`. The suggestion is written in the backticked
  form, and the note says that `accepted` takes option 1.
- A question already open: an open technical question with no `### Clarifier suggestion` block, whose option 1 has
  either form, takes that option as its suggestion.
  - `l4 questions show` names it as what `accept` takes. JSON: `accept.takes`, plus `accept.from: "option 1"`.
  - `l4 questions accept`, and the delegate's `accept`, which uses the same edit core (`build_edit`), first write the
    block with the backticked form, then set Status `accepted`.
  - A block that exists, an `(empty)` one included, is never replaced: a clarifier that wrote it decided.
- The delegate's prompt says that a frozen test file opens only through `accept` of the clarifier suggestion, and that
  an `answer` that names a frozen path is refused.
- Every unfreeze rule stays:
  - the question itself must name the file;
  - the delegate's accept opens test files only, and nothing in a fix task;
  - an agent caller is held to `clarifier.answer_by_agents`.

## Impact

- Code:
  - `l4.specs.questions`: `edit_option`, `option_suggestion`, `accept_text`, `QuestionsFile.with_option_suggestion`;
  - `l4.specs.questions_cli`: `check_question`, `build_edit`, `run_show`, `agent_refusal`, `suggestion_effects`;
  - `l4.implementer.loop`: `_with_note`, `_suggest_edits`;
  - `l4.delegate.reply`, `l4.delegate.run` (the view in the prompt), `l4.delegate.prompt`.
- Behaviour:
  - a bare-path option 1 is a suggestion;
  - an open question raised before 0.4.39 is accepted without another implementer round;
  - nothing else is unfrozen that was not before.
- Docs:
  - requirements L4-IMP-004 and L4-QMD-008 (the span `accept` adds), and L4-DLG-014 (the prompt line);
  - scenarios SCN-IMP-418 and SCN-IMP-419, SCN-QMD-29 and SCN-QMD-30, SCN-DLG-122;
  - change-table row 85, CHANGELOG 0.4.39.
