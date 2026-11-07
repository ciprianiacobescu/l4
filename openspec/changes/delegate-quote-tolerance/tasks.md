## 1. The rules (D1 to D4)

- [x] 1.1 Write the tests first, in a new file `tests/unit/delegate/test_reply_quote_tolerance.py` (import `check`,
  `cite`, `reply`, `FILES` and `UNIT_REL` from `.test_reply`, as `test_reply_0421.py` does; build each head as
  `HeadTree({p: True for p in files}, lambda p: files.get(p), UNIT_REL)`): SCN-DLG-134 to SCN-DLG-143, each at the
  `check_reply` level (a `Kept` or a `Discarded` with `checked <ref> does not resolve` and `retryable` true), and also:
  - a placed entry's `Kept.checked` item is the delegate's entry plus `resolved` (`ref`, `quote` and `claim`
    unchanged), and an entry resolved at its cited line, a `spec:` entry and a `test:` entry have no `resolved`;
  - a range ref `AGENTS.md:1-5` whose quote is at line 63 only is placed with `resolved: AGENTS.md:63`;
  - a cited line past the end of the file (`AGENTS.md:500`) with a quote the file holds once is placed;
  - overlapping occurrences: a file line `ab ab ab ab ab ab ab` and the quote `ab ab ab ab ab` cited 10 lines away do
    not resolve (two offsets, though `str.count` finds one);
  - the line of a match (D2) after blank lines, after lines whose `**` the fold removed, and in a file with `\r\n`
    line ends;
  - a quote the file holds once before the window and nowhere from `line - 3` on is placed at that earlier line;
  - an entry that resolves today (`src/pkg/store.py:42` with `return hash_password(raw, cost=12)`) is kept with no
    `resolved`, also when the file holds the quote a second time far below;
  - a harness-written file, a symlink and a quote under 12 characters keep their refusals when the quote is in the file
    once, far from the cited line.

  Then change `src/l4/delegate/reply.py`: add `MARKDOWN_SUFFIXES = (".md", ".markdown")`, `_EMPHASIS =
  re.compile(r"\*\*")`, `_flat_md(text)` (`_flat(_EMPHASIS.sub("", text))`), `_folds(path, quote)` (`(_flat,)`, plus
  `_flat_md` when `PurePosixPath(path).suffix.lower()` is in `MARKDOWN_SUFFIXES` and `len(_flat_md(quote)) >=
  MIN_QUOTE_CHARS`), `_in_window(lines, line, q, fold)` (today's window test with `fold` in place of `_flat`),
  `_line_of(lines, fold, at)` (D2, one pass with a running length) and a frozen dataclass `Resolved(at: str | None =
  None)`. `_resolves` returns `Resolved | None`: the `test:` branch as today; the `spec:` branch tries each fold of
  `_folds(chosen, entry["quote"])`; the `path:line` branch follows D1 (all windows first, then the exactly-one search;
  the quote must be alone in every fold in which it occurs, and the first fold in which it occurs gives the line). Keep every guard of today in its place and order. In
  `_check_reply`, collect the `at` of each entry and build the `Kept.checked` tuple with `{**entry, "resolved": at}`
  where `at` is set; `_cites_file`, `_recorded`, the refusal texts and `prompt.py` do not change. Update the module and
  `_resolves` docstrings (L4-DLG-005, delegate-quote-tolerance).

- [x] 1.2 Update the guards of `tests/unit/delegate/test_reply.py` that the placed rule turns into resolutions (checked
  with a prototype of D1 against these fixtures; run the file to find any other):
  - `test_checked_entries_resolve` (SCN-DLG-16): `src/pkg/store.py:46` and `src/pkg/store.py:38` now resolve, placed at
    `src/pkg/store.py:42`. Keep both as negatives against a head whose `src/pkg/store.py` is `STORE` plus the quote a
    second time at its end (line 51), and move the single-copy cases into the new file as positives with `resolved:
    src/pkg/store.py:42`. The `ok` entries `:42`, `:45`, `:39` still resolve at their cited line.
  - `test_a_wrapped_sentence_quoted_as_one_line_resolves` (SCN-DLG-116): the three `far` entries now resolve, placed at
    `src/pkg/wrapped.md:39`, `src/pkg/wrapped.md:39` and `src/pkg/wrapped.md:50`. Assert that, and keep the negative
    with `WRAPPED_TEXT` plus a second copy of each sentence appended: then each `far` entry does not resolve. `near`
    (`:47`) still resolves at its cited line.
  - `test_a_repository_gate_script_is_evidence` (SCN-DLG-120): `far` (`.l4/gates/test.sh:20`) now resolves, placed at
    `.l4/gates/test.sh:3`; assert it; `wrong` keeps `does not resolve`.
  Update the comments that say a quote four lines off, or further down than three lines, does not resolve.

- [x] 1.3 In `tests/unit/delegate/test_pass.py`, add one test through the pass: a reply whose only `checked` entry is
  `{"ref": f"{UNIT_DIR}/proposal.md:1", "quote": QUOTE, "claim": "…"}` (the fixture's `proposal.md` holds `QUOTE` once,
  at line 8) is answered on the first call, and its `delegate.result` has `checked[0]["ref"] ==
  f"{UNIT_DIR}/proposal.md:1"` and `checked[0]["resolved"] == f"{UNIT_DIR}/proposal.md:8"`; the default `reply()`'s
  answered result has no `resolved` key. No change in `src/l4/delegate/run.py` is expected; if one is needed, write it
  into this task's result.

## 2. Docs and checks

- [x] 2.1 `tests/unit/docs/test_delegate_docs.py`: the scenarios of later changes are `range(116, 144)` (this change
  adds SCN-DLG-134..143 to docs/SPEC.md, which the `delegate-answers` change does not hold); add the change's name to
  the comment. docs/SPEC.md (L4-DLG-005, SCN-DLG-16, SCN-DLG-116, SCN-DLG-134..143, the `delegate.result` record of
  §12.1, row 120) and CHANGELOG.md are written by the spec commit of this change: edit them only to correct a mismatch
  with the code, and say so in the result.

- [x] 2.2 Run, once with pytest (never in a loop, never two runs at once, no `while pgrep` wait, never the whole
  suite), in one invocation: `tests/unit/delegate/test_reply_quote_tolerance.py`, `tests/unit/delegate/test_reply.py`,
  `tests/unit/delegate/test_reply_0421.py`, `tests/unit/delegate/test_pass.py`, `tests/unit/delegate/test_batch.py`,
  `tests/unit/delegate/test_prompt.py`, `tests/unit/delegate/test_review_fixes.py`,
  `tests/unit/delegate/test_worktree_mask.py`, `tests/unit/verifier/test_delegate_fix_unit.py`,
  `tests/unit/docs/test_delegate_docs.py` and `tests/unit/docs/test_check_spec.py`. Then `ruff check` and `ruff format
  --check` on the changed files, `python scripts/check_spec.py docs/SPEC.md`, and `openspec validate
  delegate-quote-tolerance --strict`. Report the counts.
