# The delegate's citations resolve as a person reads them, and one that does not is asked again

## Why

In one consumer delivery plan, three of the delegate's four discarded replies on one day were good answers whose
`checked` references did not resolve, and each discard escalated its question to a person and stopped the plan
[V, ledgers `delegate.result{status: discarded}`]:

- twice `spec:spec.md#requirement-…` for the unit's `specs/<capability>/spec.md`. The prompt shows every document
  of the unit under its repository path (`openspec/changes/<unit>/specs/<capability>/spec.md`), while a `spec:`
  reference must be relative to the unit's folder; the delegate wrote the file's bare name [V, code: `_resolves`,
  `build_prompt`; probe on the consumer's head: `spec:spec.md#…` false, the folder-relative path true];
- once `openspec/changes/<unit>/design.md:40`. A `path:line` quote is compared with windows of exactly as many lines
  as the quote has, so a sentence that wraps over two lines of the file, quoted as one line, never resolves
  [V, code and probe: the same text is false as one line and true with the file's line break]. That this is what the
  delegate quoted there is inferred [I]: a discarded reply's quotes are not recorded.

Each of these calls cost between 1.26 and 1.80 dollars, and the question then waited for a person although the
answer was right. A discard escalates at once (`check_reply` → `_escalate`), while a timeout or an adapter error is
asked again within `delegate.max_attempts_per_question` (default 2).

## What Changes

- A `path:line` entry resolves when its quote, with whitespace folded, starts within three lines of the named line
  (the first occurrence at or after line `line - 3` starts at or before the end of line `line + 3`), whatever line
  breaks the quote keeps. A quote found only further from the line still does not resolve.
- A `spec:` entry also resolves its file by the repository path the prompt shows (`openspec/changes/<unit>/…`), and by
  a bare file name when exactly one tracked file of the unit's folder has that name. Two files of that name, a path
  outside the folder, or a harness-written file still do not resolve.
- The prompt (`delegate@4`) names the reference form with an example (`spec:specs/<capability>/spec.md#<anchor>`).
- A discarded reply's `delegate.result` records its `checked` entries' `ref` and `quote`, redacted, so the next
  discard can be read.
- A reply discarded only because a `checked` entry does not resolve is asked again once more, within
  `delegate.max_attempts_per_question`: `delegate.result{status: deferred}` with the discard reason, and the next
  prompt says why the previous reply was discarded and how a reference is written. Any other discard, and a second
  one, escalates as today.

## Impact

- Code: `l4.delegate.reply` (`_resolves`, `Discarded`), `l4.delegate.prompt` (the reference rule, a `previous`
  block, `PROMPT_VERSION` 4), `l4.delegate.run` (the discard branch, the material of the next ask).
- Security: every rule still needs the quote word for word in a tracked, regular, non-harness file at the unit head;
  nothing that did not resolve before resolves to a different file than the one the reference names. A retry costs
  at most one more call per question and stays under the attempt and cost limits.
- Docs: L4-DLG-005 (references, the recorded entries, the retry), SCN-DLG-116..119, change-table row 77, CHANGELOG.
- Out of scope (backlog): intake turning design "Open questions" that are statements into questions; the per-task
  answer limit.
