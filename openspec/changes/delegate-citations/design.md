# Design: the delegate's citations

## D1. A `path:line` quote starts within the window

`_resolves` today tries windows `lines[start-1 : start-1+span]` for `start` in `line-3 .. line+3`, where `span` is
the number of lines of the quote as written. A quote of wrapped prose written as one line has `span` 1 and never
matches. New rule, with `W = LINE_WINDOW` (3) and `_flat` folding whitespace:

- `a = max(line - W, 1)`; `head = _flat("\n".join(lines[a-1 : line+W]))` (the window) and
  `rest = _flat("\n".join(lines[a-1:]))` (from the window to the end of the file);
- the entry resolves when `0 <= rest.find(quote) < len(head)`: the quote's first occurrence at or after line `a`
  starts inside the window. `quote` is `_flat(entry["quote"])` as today, and the length floor stays.

A quote that starts after the window (four lines off, or further down the file) does not resolve; a quote that
starts in the window and runs past it does. `rest.find` returns the first occurrence, so a later one is never
needed: if the first starts after the window, every other does too.

## D2. Which file a `spec:` entry names

The prompt shows each document of the unit under its repository path (`path=` of its data block), and the rule asks
for a path relative to the unit's folder. `_spec_file(name, head)` returns the repository path of the file, tried in
this order, each only when the result is a tracked regular file (`head.tracked.get(path)` true):

1. `f"{head.unit_rel}/{name}"`, as today;
2. `name` itself, when it starts with `head.unit_rel + "/"` (the path the prompt shows);
3. when `name` has no `/`: the one tracked regular file under `head.unit_rel + "/"` whose last path part is `name`;
   none, or more than one, is no file.

`_safe_relative` runs on `name` first, and `_harness_written` on the chosen path, as today; the quote must be in that
file (`quote in _flat(text)`). A name that resolves by none of the three is `checked <ref> does not resolve`, and the
reason keeps the ref as written.

## D3. The prompt, `delegate@4`

The reference sentence of the system text becomes: `` `spec:<file>#<anchor>` for a file of the unit's folder, the path
relative to the folder: `spec:design.md`, `spec:specs/<capability>/spec.md#<anchor>` ``, and the `path:line` sentence
adds that the line is where the quote starts. `PROMPT_VERSION` goes from 3 to 4 (the version names the prompt's
rules).

A new optional `Material.previous: str = ""` (the reason of the previous discard). When it is not empty,
`build_prompt` adds, after the question block, `# Your previous reply` with a data block (kind `previous`, source
`harness`) holding `The previous reply to this question was discarded: <reason>. Write each reference in the form the
rules give; the quote is copied word for word.` (redacted, capped like the other pieces).

## D4. What a discarded reply records

`Discarded` gains `checked: tuple[dict[str, str], ...] = ()`. `check_reply` fills it, once the reply is a valid
`l4/delegate-result@1` document, with each entry's `ref` and `quote` (not its `claim`), each redacted with the
redactor it is given; the existing length limits (20 entries, ref 300, quote 600) already bound them, and a reply
that breaks those limits records nothing. In `run.py`, the discard branch passes `checked=kept.checked` to
`_escalate` (and to the deferral of D5), so `delegate.result{status: discarded}` holds `checked: [{ref, quote}]`.
The answer `text` is still never recorded.

## D5. One more ask for a reference that did not resolve

`Discarded` gains `retryable: bool = False`; `check_reply` sets it only where it returns `checked <ref> does not
resolve` (which includes a quote under 12 characters). A harness-written file, a missing `checked` entry, the text
checks and every other rule stay not retryable. In `run.py`'s discard branch:

- `retryable` and `attempts_used(events, key) + 1 < max_attempts_per_question`: `_defer(target, key, shared, why,
  now + RETRY_AFTER_S, who, reply)` with `why = "the reply was discarded: <reason>; it is asked again"`, and the
  result also records `discarded: <reason>` and `checked` (D4). The question stays open and gets no `Escalated by:`
  line; `delegate.due` already asks a deferred question again once `retry_after` has passed, and `attempts_used`
  counts this call.
- otherwise: `_escalate` as today (with `checked`).

The prompt builder reads the latest result of the question's current raise (`limits._results(events, key)`): when it
is `deferred` and has `discarded`, `Material.previous` is that reason.

## D6. What stays

`test:` entries, the 12-character floor, the harness-written rule, the entry limits, `escalate` replies (refs only),
the kinds' decisions, every other discard reason and the `Escalated by:` text of an escalation.
