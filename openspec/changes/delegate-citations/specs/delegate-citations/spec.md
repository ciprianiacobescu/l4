## Purpose

A `checked` reference of the delegate resolves when its quote is where a person reading the reference would find it,
and a reply discarded only for a reference that did not resolve is asked once more instead of stopping for a person.

## ADDED Requirements

### Requirement: A path:line quote starts within three lines of the line
A `path:line` entry SHALL resolve when its quote, with whitespace folded, starts within three lines of the named line:
the quote's first occurrence at or after line `line - 3` (at least line 1) starts in the folded text of lines
`line - 3` to `line + 3`. The quote MAY run past that window and MAY be written without the file's line breaks. A quote
whose first occurrence from line `line - 3` on starts after the window SHALL NOT resolve.

#### Scenario: a wrapped sentence quoted as one line
- **WHEN** a sentence wraps over lines 39 and 40 of `design.md` and an entry `design.md:40` quotes it as one line
- **THEN** the entry resolves

#### Scenario: a quote four lines off
- **WHEN** the quote starts at line 42 and the entry names line 46
- **THEN** the entry does not resolve

### Requirement: A spec reference names a file of the unit's folder in the forms the prompt shows
A `spec:<name>` entry SHALL resolve to, in this order: `<unit folder>/<name>`; `<name>` when it starts with the unit
folder's repository path; for a `<name>` without `/`, the one tracked regular file under the unit folder whose file
name is `<name>`. Two or more such files, none, a path outside the unit folder or a harness-written file SHALL NOT
resolve, and the quote MUST be in the chosen file.

#### Scenario: the bare name of the unit's only spec delta
- **WHEN** the unit folder holds one `specs/<capability>/spec.md` and an entry is `spec:spec.md#requirement-x` with a
  quote from that file
- **THEN** the entry resolves

#### Scenario: the bare name of two spec deltas
- **WHEN** the unit folder holds `specs/a/spec.md` and `specs/b/spec.md` and an entry is `spec:spec.md`
- **THEN** the entry does not resolve

#### Scenario: the repository path the prompt shows
- **WHEN** an entry is `spec:openspec/changes/<unit>/design.md` with a quote from that file
- **THEN** the entry resolves

### Requirement: A reply discarded for a reference that did not resolve is asked again once
A reply discarded only because a `checked` entry does not resolve SHALL be asked again when the question has an
attempt left under `delegate.max_attempts_per_question`: `delegate.result{status: deferred}` records the discard
reason (`discarded`) and the entries, the question stays open with no `Escalated by:` line, and the next prompt
(`delegate@4`) SHALL say why the previous reply was discarded. With no attempt left, or for any other discard, the
question SHALL be escalated as before. Every discarded reply's `delegate.result` SHALL record its `checked` entries'
`ref` and `quote`, redacted, never its text.

#### Scenario: a first discard for a reference is asked again
- **WHEN** the delegate's first reply cites `spec:spec.md` in a folder with two spec deltas
- **THEN** `delegate.result` is `deferred` with `discarded` and `checked`, the question has no `Escalated by:` line,
  and the next ask's prompt holds the reason

#### Scenario: the second discard escalates
- **WHEN** the asked-again reply is discarded for a reference too
- **THEN** `delegate.result` is `discarded` with `checked`, and the question is escalated

#### Scenario: a harness-written citation escalates at once
- **WHEN** the first reply cites `spec:questions.md`
- **THEN** the question is escalated with no second ask
