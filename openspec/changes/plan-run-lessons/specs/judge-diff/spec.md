## Purpose

The judge reads all of a unit's work and none of the harness's bookkeeping, a diff longer than one prompt is judged in
parts instead of being cut, and what the judge still cannot see is a person's decision, never a fix unit.

## ADDED Requirements

### Requirement: L4-VER-040 The judge's diff leaves out the harness's bookkeeping, named once
The diffs the judge and the S1 step read, and the length the judge step compares with the cap, SHALL leave out the
harness's bookkeeping, given by one list (`bookkeeping_pathspecs`): every path under a `.l4/` directory,
`.serena/memories/harness/**`, and `verification.md`, `questions.md` and `feedback.md` in each unit folder of the
family. The file names SHALL come from the unit folder's channel list in `l4.state.review`. A file of those names
outside the family's folders SHALL stay in the diff.

#### Scenario: SCN-VER-130 (+) The judge reads the unit's work, not the family's channel files
- **GIVEN** a unit branch that changes `src/app/report.py`, `tests/test_report.py` and `docs/questions.md`, and, in the
  unit folder and in its fix unit's folder, `questions.md`, `feedback.md`, `verification.md`, `.l4/ledger/r1.jsonl`
  and `.l4/review-accepted.json`
- **WHEN** the judge step builds its diff
- **THEN** the diff holds the three project files and no file of the two unit folders, and the length the step compares
  with 120000 is the length of that diff

### Requirement: L4-VER-041 A diff longer than one prompt is judged in parts
A diff (L4-VER-040) over 120000 characters SHALL be judged in parts, not cut: whole files, ordered so that a
test sits next to the code it is named after, packed into at most 8 parts of at most 120000 characters each (a
longer file alone, cut). Each part SHALL be one judge call: the round's prompt with the part's diff, a `part K of N`
heading, the file list, and the rule that what the part does not show is `insufficient_evidence`, not `fail`. A diff
within the cap SHALL keep its one prompt.

#### Scenario: SCN-VER-131 (+) A diff of 202000 characters is judged in two parts, with no hold
- **GIVEN** a unit whose diff after L4-VER-040 is 202000 characters in six files, with diffs of 50000
  (`src/app/export.py`), 30000 (`tests/test_export.py`), 12000 (`README.md`), 60000 (`src/app/report.py`), 40000
  (`tests/test_report.py`) and 10000 (`src/app/util.py`) characters
- **WHEN** the judge step runs
- **THEN** the judge is called once per part for two parts, the first with `src/app/export.py`, `tests/test_export.py`
  and `README.md`, the second with `src/app/report.py`, `tests/test_report.py` and `src/app/util.py`; each prompt is
  headed `part K of 2`, lists all six files with their part and holds the rules of a part (what the part does not show
  is `insufficient_evidence` with the reasoning `not in this part`, never `fail`; a `fail` cites code of the part; an
  item not in the part is false with evidence that starts with `not in this part`); the same diff gives the same two
  parts again; `verify.judge` is recorded with `part` 1 and 2 and `parts` 2; `verdict.json` lists `judge_parts`;
  `verification.md` says `judged in 2 parts`; the template is `judge@10`; and the round has no hold about the diff

#### Scenario: SCN-VER-135 (−) A diff that needs more than eight parts holds and names what the judge did not see
- **GIVEN** a unit whose diff is eleven files of 70000 characters each
- **WHEN** the judge step runs
- **THEN** eight parts are judged (eight judge calls), and the round holds `judge view: the diff needs more than 8 parts
  of 120000 characters: the judge did not see …`, naming the three files that are in no part judged

### Requirement: L4-VER-042 The parts' replies are merged into one verdict
The replies of the parts SHALL be merged into one verdict before anything reads it: per criterion a `fail` of any
part, else a `pass`, else a `not_verifiable`, else `insufficient_evidence`; a test any part calls inadequate is
inadequate; the findings of all parts without repeats; a feedback, accepted or satisfied item is true when a part says
true and no part says false with evidence other than `not in this part`. A part whose reply is discarded SHALL discard
the round's judge verdict.

#### Scenario: SCN-VER-132 (+) A criterion one part passes and another part cannot see is a pass
- **GIVEN** two part replies: part 1 says `pass` for C-1 with a citation and `addressed: true` for FB-001; part 2 says
  `insufficient_evidence` for C-1 with the reasoning `not in this part` and `addressed: false` for FB-001 with the
  evidence `not in this part`
- **WHEN** the replies are merged
- **THEN** C-1 is `pass` with the evidence of part 1, and FB-001 is addressed

#### Scenario: SCN-VER-133 (−) A fail in one part wins over a pass in another
- **GIVEN** part 1 says `pass` for C-2 and calls the test T adequate for C-2, and part 2 says `fail` for C-2 with a
  counterexample on code of part 2 and calls T inadequate for C-2
- **WHEN** the replies are merged
- **THEN** C-2 is `fail` with the counterexample of part 2, and T is inadequate for C-2

#### Scenario: SCN-VER-134 (−) A part that shows an item undone keeps it open
- **GIVEN** part 1 says `addressed: true` for FB-002, and part 2 says `addressed: false` for FB-002 with the evidence
  `src/app/export.py:40 still writes the old header`
- **WHEN** the replies are merged
- **THEN** FB-002 is not addressed, with the evidence of part 2

#### Scenario: SCN-VER-136 (−) A part whose reply is discarded discards the judge's verdict
- **GIVEN** a diff in two parts whose second part's reply breaks the schema twice
- **WHEN** the judge step runs
- **THEN** the round has no judge verdict, it holds `the judge's reply was discarded (part 2 of 2, schema_invalid: …)`,
  and no verdict of part 1 is counted

### Requirement: L4-VER-043 What the judge could not see is a hold of the kind judge_view
A file cut to one part SHALL raise the hold ``judge view: the diff of `<path>` is longer than one part (120000
characters): the judge saw only its start``, and files in no judged part a `judge view:` hold naming them. These and
the 0.4.14 hold `the diff is longer than 120000 characters: the judge saw only the start` SHALL be of the kind
`judge_view`, whose question SHALL say that `accept` means a person checked those files and that no fix unit can
shrink the diff, and ask for no `WHEN … THEN …`.

#### Scenario: SCN-VER-137 (−) A file longer than one part holds, and its question asks for no scenario
- **GIVEN** a unit whose diff holds `uv.lock` with 300000 characters of diff, and two small files
- **WHEN** the round ends
- **THEN** the judge saw the start of `uv.lock` in a part of its own, the round holds ``judge view: the diff of
  `uv.lock` is longer than one part (120000 characters): the judge saw only its start``, the hold is of the kind
  `judge_view`, and its question says that `accept` means a person checked `uv.lock` and that a fix unit cannot shrink
  the diff, and does not ask for `WHEN … THEN …`

#### Scenario: SCN-VER-139 (−) The hold text of 0.4.14 is a hold on the judge's view
- **GIVEN** a round resumed after the upgrade whose holds include `the diff is longer than 120000 characters: the judge
  saw only the start`, rejected with a `WHEN … THEN …` reason
- **WHEN** its holds are settled and the fix unit is planned
- **THEN** the hold is of the kind `judge_view`, its finding is a human one, and no fix task is made from it

### Requirement: L4-VER-044 A rejected judge_view hold never becomes a fix unit
A rejected `judge_view` hold SHALL be a human major finding (`Rejected hold: the judge could not see all of the diff`)
that no fix task is derived from, whatever its reason. A failed round with nothing else to fix SHALL escalate the unit
with `judge_view_rejected`; `l4 status --unit`, the refusal of `l4 run --unit` and the sticky note SHALL name its way
out (split the change, then `l4 restart`; or `accept` by `--replace`, then `l4 retry`), never `l4 feedback add`.

#### Scenario: SCN-VER-138 (−) A rejected hold on the judge's view never becomes a fix unit
- **GIVEN** the hold of SCN-VER-137 rejected with a reason that ends with `WHEN the diff is long THEN the judge SHALL see
  every file`, and no other finding in the round
- **WHEN** the fix loop decides
- **THEN** no fix task is planned, the unit is escalated with `judge_view_rejected`, and `l4 status --unit`, the refusal
  of `l4 run --unit` and the sticky note name splitting the change (then `l4 restart`) or replacing the answer with
  `accept` (`--replace`) and `l4 retry`, and none of them names `l4 feedback add`
