## Purpose

A suggested edit of a frozen test is taken whether the agent wrote its path in backticks or bare, and a question raised
before the harness knew the bare form is accepted without another implementer round.

## ADDED Requirements

### Requirement: L4-IMP-004 Option 1 is an edit in both forms
A technical question's first option SHALL be read as a suggested edit when it is "Edit `<path>`: <change>" or
"Edit <path>: <change>", where the bare path is one token without whitespace, backtick or colon that holds a `/` or a
`.`. The suggestion and the harness note SHALL use the backticked form.

#### Scenario: SCN-IMP-418 (+) a bare path in option 1 is the suggestion
- **WHEN** a blocked green step asks a technical question whose option 1 is `Edit tests/test_a.py: assert 2`
- **THEN** its `### Clarifier suggestion` block reads ``Edit `tests/test_a.py`: assert 2``, and the harness note says
  that `accepted` takes option 1

#### Scenario: SCN-IMP-419 (−) an option that names no file is no suggestion
- **WHEN** option 1 is `Edit the test: assert 2`
- **THEN** no suggestion block is written, and the note says to write an answer that names the path

### Requirement: L4-QMD-008 An open question takes option 1 when it has no suggestion
For an open technical question with no `### Clarifier suggestion` block whose option 1 is an edit (L4-IMP-004),
`l4 questions show` SHALL name that option, in the backticked form, as what `accept` takes (`accept.from: "option 1"` in
JSON). `l4 questions accept` SHALL add the block with that text before it sets Status `accepted`. A block that exists,
`(empty)` included, MUST NOT be replaced. The question SHALL still unfreeze only under the rules of an accepted
suggestion (L4-IMP-015).

#### Scenario: SCN-QMD-29 (+) a question raised without a suggestion is accepted
- **WHEN** an open technical question has option 1 `Edit src/app.test.ts: seed the issued secret`, no suggestion
  block, and `l4 questions accept` runs
- **THEN** the file gains the block ``Edit `src/app.test.ts`: seed the issued secret`` and Status `accepted`; the
  question reads back as answered, and its effective answer is that text

#### Scenario: SCN-QMD-30 (−) a written suggestion is kept
- **WHEN** the question has a `### Clarifier suggestion` block that reads `Take option 2` and option 1 is a bare edit
- **THEN** `show` and `accept` take `Take option 2`, the block is unchanged, and no `accept.from` is shown

### Requirement: L4-DLG-014 The delegate accepts option 1 under the same rules
The delegate's `accept` of an open question without a suggestion block SHALL take option 1 as L4-QMD-008 says and SHALL
write the block through the same edit. The rules of L4-DLG-014 (test files only, nothing in a fix task) SHALL apply. The
delegate's prompt SHALL say that a frozen test file opens only through `accept` of the clarifier suggestion.

#### Scenario: SCN-DLG-122 (+) the delegate accepts a bare-path option 1
- **WHEN** `delegate.unfreeze` is true and the delegate replies `accept` to such a question about a frozen red test of
  a held task
- **THEN** the reply is kept, the file gains the block and Status `accepted`, and `question.answered{by: delegate}`
  carries the digest of the block as the file reads it
