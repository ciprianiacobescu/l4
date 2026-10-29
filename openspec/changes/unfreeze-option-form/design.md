# Design: take option 1 as the suggestion in both forms

## D1. One parser, pure

`edit_option(text: str) -> str | None` lives in `l4.specs.questions`, next to the file model, so that the implementer,
the CLI and the delegate read the same rule.

- It matches `^Edit `(?P<path>[^`\s]+)`: (?P<rest>\S.*)$` or `^Edit (?P<path>[^`\s:]+): (?P<rest>\S.*)$`.
- In the bare form the path must hold a `/` or a `.`: "Edit the test: …" is no edit of a file.
- It returns `Edit `<path>`: <rest>`.

The path is not checked against the work tree or the freeze manifest:

- a path that names no frozen file unfreezes nothing (`unfrozen` matches the manifest's paths with `names_path`);
- what an accept passes on is the option the agent wrote itself;
- one pure rule keeps the new-question side and the open-question side equal, and needs no git at `show` time.

## D2. Materialise the block, never read one that is not there

An `accepted` question's effective answer is its suggestion block (`effective_answer`). The green step's unfreeze needs
the ledger's `question.answered` digest to equal `answer_sha256` of the question as the file reads (`unfrozen`). The
next run records that digest from the file (L4-QMD-008). So an accept must leave the block on disk.

- `QuestionsFile.with_option_suggestion(qid, *, redactor)` returns the file with the block added by `set_suggestion`
  (redacted and neutralised like every text the harness writes). It returns the file unchanged when `option_suggestion`
  is None.
- `option_suggestion(question)`: `edit_option(options[0])` for a question with Status `open`, kind `technical`, no
  `### Clarifier suggestion` block (`question.suggestion is None`), and an option 1. Otherwise None. A block that exists is
  the clarifier's or the harness's, and it stays, even one that reads `(empty)`.
- `accept_text(question)`: the suggestion as written (`unescape_text(question.suggestion_text)`), else
  `option_suggestion(question)`, else `""`. Every place that asks "what does `accept` take" reads it:
  - `check_question` (form `accept`);
  - `run_show` (`takes`);
  - `agent_refusal` (`effective`);
  - `suggestion_effects` (`text`);
  - `check_reply` (`suggestion`);
  - the delegate's prompt view (`suggestion_text` of the view the prompt is built from).
- `build_edit` with form `accept` works on `base = folder.file.with_option_suggestion(qid, redactor=redactor)`:
  - `check_question`, `question` and `edit_accept` take `base`;
  - `Edit.old` stays `folder.file`, the bytes on the branch;
  - `round_trip(folder.file, new, …)` still checks every other question.

  The CLI and the delegate's `_answer` both write through `build_edit`, so both write the block.
- `QuestionsFile.load` is NOT changed. The green step's `_unfreeze_parts`, `held.py`, the judge's answer references and
  the clarifier's ports read the file as it is, and must never see a block that is not there.
- The delegate's `_file(target)` stays as it is too. Its escalation path saves that file, and a derived block must not
  be written by an escalation.

## D3. The spans of `accept` (L4-QMD-008)

`accept` changes the Status value and the index row. For a question that takes option 1, it also adds the
`### Clarifier suggestion` block: before `### Answer`, or at the end of the section. The read-back check adds: the
question's effective answer equals `option_suggestion` of the question before the edit. `answer` is unchanged: it never
writes the block.

## D4. What `show` says

- Text: `accept takes: <text> (option 1: the question has no clarifier suggestion)`.
- JSON: `accept: {"takes": <text>, "from": "option 1"}`. The `from` key appears only then, like `existing` on a frozen
  entry.
- `next` names `l4 questions accept` as it does for a written suggestion.

## D5. The delegate's prompt line

The rules paragraph gains one sentence after the decision line: "A frozen test file is opened only by `accept` of the
clarifier suggestion: an `answer` whose text names a frozen path is refused, whatever it says." The refusal
(`reply.py`) already says so. The line saves the attempt that the consumer's delegate spent on an `answer`.

## D6. Not in scope

- Options 2 and later are never taken, as before.
- Neither form changes what `unfrozen` grants.
- A question whose option 1 is not an edit keeps no suggestion. A person answers it.
