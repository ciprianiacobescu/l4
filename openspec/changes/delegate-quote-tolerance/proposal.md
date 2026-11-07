## Why

Two consecutive units of a consumer's delivery plan each had a delegate reply discarded by the citation check
(L4-DLG-005), and each question was asked again: a new paid call, after a retry delay, and a run's delay for the unit.

- A `path:line` entry cited `AGENTS.md:1` with a sentence copied word for word from that file, where the sentence starts
  at about line 63. A `path:line` quote must start within `LINE_WINDOW` (3) lines of the named line, so the reply
  ($2.44) was discarded with `checked AGENTS.md:1 does not resolve`. When the file holds the sentence at one place
  only, the harness can say where it is.
- The next unit's delegate cited `spec:design.md` with the quote `` `parseRef(ref, hook?)`: `undefined` `U` ``, and
  line 10 of the file reads `` **`parseRef(ref, hook?)`**: `undefined` `U` `` (the identifier is neutral here; the
  form is the consumer's): markdown bold around the code span. A `spec:` quote is compared with the file with
  whitespace folded only (`quote in _flat(text)`), so the reply ($0.99) was discarded. The words and the code spans
  were the file's; only the bold markers were left out.

Neither reply quoted text that is not in the file. The check exists so that a claim rests on text that is at the unit
head, in a file that is evidence; it rejected both for how the text was located or marked up.

## What Changes

- A `path:line` entry whose quote does not start within three lines of the named line, and that the same file holds at
  exactly one place (whitespace folded, as today), resolves at the line where the quote starts. The answered
  `delegate.result` records that line on the entry as `resolved: <path>:<line>`; `ref` stays what the delegate wrote.
  A quote the file holds at two or more places, none of them within the window, or at none, does not resolve, as today.
- In a markdown file (`.md`, `.markdown`), a `spec:` or `path:line` quote is also compared with the doubled bold
  marker `**` removed from both the quote and the file. Backticks, `__`, single `*` and `_`, and every other
  character stay significant. A quote that this removal leaves shorter than 12 characters is compared as written only.
- Every comparison of today is tried first, so every entry that resolves today still resolves, at its cited line.
- The discard reason, the retry and the prompt are unchanged (`checked <ref> does not resolve`; `delegate@7` still asks
  for the line where the quote starts, at most three lines off).

## Impact

- Code: `l4.delegate.reply` (`_resolves`, its `path:line` branch and its `spec:` branch, a fold for markdown, the line
  of a match, the `resolved` key on the entries `Kept.checked` holds).
- Spec: L4-DLG-005 (amended: the resolution of `path:line` and `spec:` quotes), SCN-DLG-16 and SCN-DLG-116 (amended:
  their negative cases now need a quote the file does not hold at exactly one place), SCN-DLG-134..143, the
  `delegate.result` record in §12.1, change-table row 120.
- Behaviour: a reply that cites the right file and quotes it word for word, but names a wrong line or leaves out bold
  markers of a markdown file, is kept on the first call in place of a second paid call. No reply that is kept today is
  discarded or changed; a reply placed by the new rule records the real line.
- Not changed: the harness-written files, the tracked regular-file and safe-path rules, `MIN_QUOTE_CHARS`,
  `MAX_CHECKED` and the field limits, the `test:` rule, the `spec:` file choice (`_spec_file`), the retry rule, the
  prompt, `_recorded` (a discarded reply's record), `_cites_file`.
