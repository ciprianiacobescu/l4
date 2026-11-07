## MODIFIED Requirements

### Requirement: L4-DLG-005 (amendment, a quote the file places and markdown emphasis)
A `path:line` entry SHALL resolve at its cited line when its quote, whitespace folded, starts within three lines of the
named line (its first occurrence from line `line - 3` on starts in the folded text of lines `line - 3` to `line + 3`;
it may run past them and keep or drop the file's line breaks). When it does not, the entry SHALL resolve at the line
where the quote starts when the same file, whitespace folded, holds the quote at exactly one offset (overlapping
occurrences count); a quote that the file holds at two or more offsets, or at none, SHALL NOT resolve. The line of an
offset is the line, counted as `str.splitlines()` counts them from 1, that holds the first character of the match.
The answered `delegate.result` SHALL record an entry placed by this exactly-one rule (in either form below) with its
`ref` as the delegate wrote it and with `resolved: <path>:<line>`; an entry that resolved at its cited line, a `spec:`
entry and a `test:` entry SHALL get no `resolved` key.

In a markdown file (the suffix `.md` or `.markdown`, case-insensitive: for `spec:` the file the entry names, for
`path:line` the cited path), a quote SHALL also be compared in the emphasis-folded form: every `**` and `__` removed
from the quote and from the file, left to right, then whitespace folded. That form SHALL be used only when the quote
so folded still has at least 12 characters. A `spec:` entry SHALL resolve when its quote is in the file as written or
in that form. A `path:line` entry SHALL be compared in this order, the first that holds deciding: the window as
written, the window in that form, the exactly-one rule as written, the exactly-one rule in that form; the exactly-one
rule SHALL NOT go on to that form when the quote occurs as written at two or more offsets. Backticks, single `*` and
`_` and every other character SHALL stay significant, and no file of another suffix SHALL be folded.

Every entry that resolves today SHALL resolve as it does today (a `path:line` entry at its cited line, with no
`resolved`). The harness-written, tracked regular-file and safe-path rules, the 12-character minimum, the entry limits,
the discard reason `checked <ref> does not resolve`, its retry and the prompt (`delegate@7`) SHALL be unchanged.

#### Scenario: SCN-DLG-134 (+) a quote the file holds once resolves at its real line
- **GIVEN** a tracked `AGENTS.md` whose line 63 starts a sentence that the file holds at no other place
- **WHEN** a reply's only `checked` entry is `AGENTS.md:1` with that sentence, word for word, as its quote
- **THEN** the entry resolves, the reply is kept on the first call, and the answered `delegate.result` records the
  entry with `ref: AGENTS.md:1` and `resolved: AGENTS.md:63`

#### Scenario: SCN-DLG-135 (−) a quote the file holds twice off the line does not resolve
- **GIVEN** a file that holds the same sentence at lines 20 and 63
- **WHEN** an entry names line 1 and quotes that sentence
- **THEN** the reply is discarded with `checked <ref> does not resolve`, retryable, and the retry's prompt says why as
  before; the same entry naming line 61 resolves at its cited line with no `resolved`

#### Scenario: SCN-DLG-136 (−) a quote that only another file holds does not resolve
- **WHEN** an entry names `AGENTS.md:1` and quotes a sentence that `docs/guide.md` holds once and `AGENTS.md` does not
- **THEN** the reply is discarded with `checked AGENTS.md:1 does not resolve`

#### Scenario: SCN-DLG-137 (+) a quote within the window keeps its cited line
- **WHEN** an entry names line 40 of a file whose line 42 starts the quote and whose line 90 holds it again
- **THEN** the entry resolves at its cited line, with no `resolved`

#### Scenario: SCN-DLG-138 (+) a spec quote without the bold of the file resolves
- **GIVEN** a unit's `design.md` whose line 10 reads `` **`parseRef(ref, hook?)`**: `undefined` `U` ``
- **WHEN** an entry `spec:design.md` quotes `` `parseRef(ref, hook?)`: `undefined` `U` ``
- **THEN** the entry resolves and the reply is kept; `spec:design.md` quoting the line with its `**` resolves too

#### Scenario: SCN-DLG-139 (+) a markdown path:line quote without emphasis markers resolves
- **WHEN** an entry names line 10 of `docs/guide.md` or of a unit's `design.md`, the line reads
  `The __limit__ is **twenty** entries per reply.`, and the quote is `The limit is twenty entries per reply.`; or the
  entry names line 1 and the file holds that text at line 10 only
- **THEN** the first entry resolves at its cited line, and the second resolves with `resolved: <path>:10`

#### Scenario: SCN-DLG-140 (−) backticks and single markers stay significant
- **WHEN** a markdown file holds `` **`parseRef(ref, hook?)`**: `undefined` `U` `` and
  ``Call `_snake_case_name_` from the loader.`` and ``The *only* rule that holds here.``, and the quotes are
  `parseRef(ref, hook?): undefined U`, ``Call `snake_case_name` from the loader.`` and `The only rule that holds here.`
- **THEN** none resolves, while ``Call `_snake_case_name_` from the loader.`` quoted as written resolves

#### Scenario: SCN-DLG-141 (−) a quote that differs by more than emphasis markers does not resolve
- **WHEN** a markdown file holds `` **`parseRef(ref, hook?)`**: `undefined` `U` `` and the quote is
  `` `parseRef(ref, hook)`: `undefined` `U` `` (one character more than the markers is missing)
- **THEN** the reply is discarded with `checked <ref> does not resolve`

#### Scenario: SCN-DLG-142 (−) emphasis markers are folded in markdown files only
- **WHEN** an entry names line 3 of `src/app.py`, whose line 3 is `def build(**kwargs):`, with the quote
  `def build(kwargs):`; or a `spec:` entry names a `.json` file of the unit folder and drops a `**` it holds
- **THEN** neither resolves

#### Scenario: SCN-DLG-143 (−) a quote that is only markers matches nothing
- **WHEN** an entry quotes `____________` (12 underscores) or `************` from a markdown file that holds neither,
  or `**Note:** see` (13 characters, whose folded form `Note: see` has 9) from a file that holds `Note: see`
- **THEN** none resolves: such a quote is compared as written only
