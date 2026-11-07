## Context

`check_reply` (`src/l4/delegate/reply.py`) keeps a delegate reply only when every `checked` entry resolves at the unit
head (L4-DLG-005). Before resolution it refuses a harness-written file (`_harness_ref`) and a quote under
`MIN_QUOTE_CHARS` (`_too_short`, 12 characters, whitespace folded); `_resolves` then decides:

- `test:<id>`: the id is in the latest test report.
- `spec:<name>`: `_spec_file` chooses one tracked regular file of the unit folder, and the quote, whitespace folded
  (`_flat`), is a substring of the file, whitespace folded.
- `<path>:<line>` (`_LINE_REF`, an optional `-<end>` is ignored): the path is safe, tracked, regular and not
  harness-written, and the quote's first occurrence from line `line - 3` on (at least line 1) starts in the folded
  text of lines `line - 3` to `line + 3` (`LINE_WINDOW`).

An entry that does not resolve discards the whole reply with `checked <ref> does not resolve` (retryable): the pass
defers the question and asks it once more within `delegate.max_attempts_per_question`, the next prompt saying why
(`_previous_part`). A kept reply's entries (`Kept.checked`, the delegate's `ref`, `quote` and `claim`) are recorded on
`delegate.result{status: answered, checked}` by `_Pass._answer` (`src/l4/delegate/run.py`). `questions.md` holds the
answer's text only, never the entries, and no status line shows them (`l4.delegate.lines`).

## Goals / Non-Goals

**Goals:** a quote that is in the cited file word for word, and that the harness can place without doubt, resolves
when the delegate named a wrong line; a quote of a markdown file that leaves out its bold or strong markers resolves.
Every entry that resolves today resolves the same way. A quote must still be text of that file at the head.

**Non-Goals:** other markdown markup (links, single `*`/`_` emphasis, strikethrough, escapes, list and heading
markers, table pipes); typographic quotes and dashes; quotes that span files; a change to the prompt, to the retry,
to the discard reason, to the harness-written rule or to `_spec_file`; a record for discarded replies beyond what
`_recorded` keeps.

## Decisions

### D1. The order of the comparisons

For a `path:line` entry, with `lines = text.splitlines()` and line numbers counted from 1 as the window counts them:

1. **As cited.** For each fold in order (D3: `_flat`; then, in a markdown file, `_flat_md`), the window rule of today
   with that fold applied to the quote and to the lines. The first that holds resolves the entry at its cited line.
2. **Placed by the file.** Only when no window holds: for each fold in the same order, the folded quote `q` is looked
   for in the folded file `whole = fold("\n".join(lines))`. A fold in which `q` does not occur is passed over. In the
   first fold in which it occurs, it SHALL occur at exactly one offset (`whole.find(q, at + 1) == -1` for
   `at = whole.find(q)`, so overlapping occurrences count): the entry then resolves at the line of that offset (D2).
   Two or more offsets: the entry does not resolve, and the next fold is not tried.
3. Otherwise the entry does not resolve.

A `spec:` entry resolves when, for some fold in the same order, the folded quote is a substring of the folded chosen
file. It has no line, so step 2 does not apply to it, and a quote that the file holds more than once resolves as
today.

So the window is decided before the file is searched: a quote within three lines of the named line resolves there
whatever else the file holds, and the cited line is never overridden. Each new comparison runs only after the
comparisons of today failed, so the set of resolving entries grows and none leaves it.

*Alternative rejected:* a wider window. The first case was about 62 lines off; any width is arbitrary, and a wide
window still accepts a quote that occurs twice in it without saying which one is meant.

*Alternative rejected:* the file anywhere, however often. With two occurrences the cited line is the only thing that
says which one the claim is about; the harness could not name the place a person should read.

### D2. The line of a match

The line of an offset `at` of `whole = fold("\n".join(lines))` is the smallest `n` (from 1) for which
`len(fold("\n".join(lines[:n]))) > at`: the line that holds the first character of the match. It is exact because
both folds work line by line: whitespace folding joins the folded non-empty lines with one space, and the markers of
D3 never span a line break, so the folded text of the first `n` lines is a prefix of `whole`, and `at` (the start of
a quote that has no leading space) never falls on a joining space. A helper `_line_of(lines, fold, at)` computes it in
one pass: a running length that adds `len(fold(line))`, plus 1 for the joining space when the running length is not
0 and the folded line is not empty, and returns `n` at the first line where the running length exceeds `at`.

### D3. Markdown emphasis: doubled markers only, both sides, markdown files only

`_flat_md(text) = _flat(re.sub(r"\*\*|__", "", text))`: the doubled markers are removed left to right (`***` leaves
`*`), then whitespace is folded. It applies when the file the entry resolves to has the suffix `.md` or `.markdown`
(case-insensitive): for `spec:` the file `_spec_file` chose, for `path:line` the cited path. It is applied to the quote
and to the file alike, so the comparison stays symmetric: a quote that keeps the markers matches as before, one that
drops them matches a file that has them, and one that adds them matches a file that has none.

- **Doubled only.** A single `_` is part of identifiers (`_snake_case_name_`, `MAX_CHECKED`) and a single `*` is a glob,
  a pointer, a list marker or a product sign; removing them would let a quote that names another identifier or
  another glob match. `**` and `__` are strong emphasis in markdown prose and, between letters, rare in identifiers.
- **Backticks stay.** A code span marks code; a quote that drops its backticks has turned code into prose, and the
  delegate of the second case kept them. Removing them would also let `` `a` `b` `` match `` `a b` ``.
- **Markdown files only.** In code, `**kwargs`, `a ** b`, `__init__` and `__name__` are the text itself: in a
  Python file the quote `def build(kwargs)` must not match `def build(**kwargs)`.
- **A quote that is only markers matches nothing.** A quote such as `____________` (a markdown rule) or a row of `*`
  passes `_too_short` and folds to the empty string, which is a substring of every file. The fold is therefore used
  only when `len(_flat_md(quote)) >= MIN_QUOTE_CHARS`; otherwise the quote is compared as written (`_flat`) only.

*Consequence, accepted:* in a markdown file, a doubled marker inside a code span is removed too, so `` `__init__` ``
and `` `init` `` compare equal there. The quote's other characters, its backticks included, must still be the file's,
and the difference is markup a reader of the rendered file does not see as a different word.

### D4. The record names the real line, and `ref` stays the delegate's

An entry placed by step 2 of D1 is kept in `Kept.checked` as the delegate wrote it plus one key,
`resolved: "<path>:<line>"` (the safe relative path as `_resolves` read it, and the line of D2), for example
`{"ref": "AGENTS.md:1", "quote": "…", "claim": "…", "resolved": "AGENTS.md:63"}`. The answered `delegate.result`
records `checked` from `Kept.checked` (run.py, `_answer`), so the ledger carries it with no change in `run.py`. An
entry resolved as cited, a `spec:` entry and a `test:` entry get no key. `ref` is not rewritten (for example to
`AGENTS.md:63 (cited as :1)`): `_cites_file` reads the entries' `ref` with `_LINE_REF.fullmatch` for the judge-view
and cap-only rules, and the record should keep what the delegate wrote next to what the harness found. Nothing else
shows `checked`, and nothing is added: `questions.md` holds the answer's text, the status lines (`l4.delegate.lines`)
name decisions only. `_recorded` (the entries of a discarded reply) is unchanged: a discarded reply's entries record
`ref` and `quote` only.

`_resolves` returns `Resolved | None` in place of a bool: `None` when the entry does not resolve, else
`Resolved(at=None)` (as cited, `spec:`, `test:`) or `Resolved(at="<path>:<line>")`. A frozen dataclass keeps the
falsy cases apart (an empty string would read as "does not resolve").

### D5. The reason, the retry and the prompt are unchanged

A reply that still does not resolve is discarded with `checked <ref> does not resolve`, retryable, and the retry's
prompt says, as today, `The previous reply to this question was discarded: checked <ref> does not resolve. Write each
reference in the form the rules give; the quote is copied word for word.` After D1 such an entry is a quote that the
file does not hold, or holds at two or more places none of which is within the window. Naming the lines of the
occurrences in the reason was considered and left out: the case is rare, the reason string is asserted word for word
by the pass, batch, limits and prompt tests and the escalation text, and a list of lines invites the delegate to pick
one without reading the file again.

The prompt stays `delegate@7`, and still asks for "the line where the quote starts, at most three lines off" and a
quote "copied word for word". The tolerance is the harness's, so that a slip costs nothing; the instruction to the
delegate does not loosen, and the prompt's template lock is not regenerated.

### D6. Why neither rule weakens the check

The check is there so that the delegate's claims rest on text that exists at the unit head, in a file that is
evidence, and so that an invented quote discards the reply (review F6, D7 of `delegate-answers`). After this change:

- The quote is still compared with the cited file only, at the head, after the harness-written, tracked, regular-file
  and safe-path rules and the 12-character minimum, all unchanged. A quote that is in another file and not in the
  cited one does not resolve.
- The placed rule accepts a wrong line only when the file holds the quote at one place, so the harness names that
  place with certainty and records it; a person who reads the record reads the line the quote is on. The line was a
  locator for a person, which the window already allowed to be off by three; a line number says nothing that the
  quote copied from the file does not say better.
- The emphasis fold removes only `**` and `__`, in markdown, on both sides, and never leaves a quote shorter than the
  minimum. Every word, code span, digit and punctuation mark of the quote must still be the file's, in order.

## Risks / Trade-offs

- A delegate that names a wrong line has its reply kept where it would have been asked again. Its claim was never
  checked against the line, only against the quote, and the record names the real line.
- In a markdown file, `__init__` and `init` (and `a ** b` and `a b`) compare equal. The quote is still at least 12
  characters of the file's text in order; a doubled marker is the only thing that may differ.
- Each `path:line` entry that fails the window is searched in the whole file, once or twice (at most `MAX_CHECKED`
  entries, of files the check already reads). No other file is read.
