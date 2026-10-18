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

#### Scenario: SCN-VER-143 (−) A channel-named file outside the family's folders stays in the diff
- **GIVEN** a unit branch that changes `docs/questions.md`, and the `questions.md`, `feedback.md` and `.l4/ledger/r1.jsonl`
  of the unit's folder and of a folder that is no unit of the unit's family
- **WHEN** the judge step builds its diff
- **THEN** the diff holds `docs/questions.md` and the `questions.md` and `feedback.md` of the folder outside the family,
  and not the unit folder's `questions.md` and `feedback.md`; no `.l4/` file of either folder is in it

### Requirement: L4-VER-041 A diff longer than one prompt is judged in parts
A diff (L4-VER-040) over 120000 characters SHALL be judged in parts, not cut: whole files, a test next to the code it
is named after or imports, at most 8 parts of at most 120000 characters (a longer file alone, cut). Each part SHALL be
one judge call: the round's prompt with the part's diff, `part K of N`, a capped file list, and the rule that a
criterion whose code the part does not show is `insufficient_evidence`, not `fail`. A diff within the cap keeps one
prompt.

#### Scenario: SCN-VER-131 (+) A diff of 202000 characters is judged in two parts, with no hold
- **GIVEN** a unit whose diff after L4-VER-040 is 202000 characters in six files, with diffs of 50000
  (`src/app/export.py`), 30000 (`tests/test_export.py`), 12000 (`README.md`), 60000 (`src/app/report.py`), 40000
  (`tests/test_report.py`) and 10000 (`src/app/util.py`) characters
- **WHEN** the judge step runs
- **THEN** the judge is called once per part for two parts, the first with `src/app/export.py`, `tests/test_export.py`
  and `README.md`, the second with `src/app/report.py`, `tests/test_report.py` and `src/app/util.py`; each prompt is
  headed `part K of 2`, lists all six files with their part and holds the rules of a part (a criterion whose code the part does not show
  is `insufficient_evidence` with the reasoning `not in this part`, never `fail`, and a criterion whose code it shows is judged there, whichever part holds its test; a test it does not show is left out of `test_adequacy`; a `fail` cites code of the part; an
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
part, else a `pass`, else a `not_verifiable`, else `insufficient_evidence`; a test is inadequate when a part that sees
it says so; the findings of all parts without repeats; a feedback, accepted or satisfied item is true when a part says
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
- **GIVEN** a unit whose diff holds `data/seed.json` with 300000 characters of diff, and two small files
- **WHEN** the round ends
- **THEN** the judge saw the start of `data/seed.json` in a part of its own, the round holds ``judge view: the diff of
  `data/seed.json` is longer than one part (120000 characters): the judge saw only its start``, the hold is of the kind
  `judge_view`, and its question says that `accept` means a person checked `data/seed.json` and that a fix unit cannot shrink
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

#### Scenario: SCN-YOLO-149 (−) A judge-view reject beside another unconvertible reject names each way out
- **GIVEN** a failed round with a rejected `judge view:` hold and another finding of a person that no fix task can be
  derived from
- **WHEN** the fix loop decides
- **THEN** the unit escalates with a cause that names both, and `l4 status --unit` gives the feedback way out and the
  way out of the hold on the judge's view

### Requirement: L4-VER-045 A lock file is one line for the judge, never a diff
A file whose old and new base names are both lock files (`uv.lock`, `poetry.lock`, `Pipfile.lock`,
`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `go.sum`, `Cargo.lock`, `composer.lock`, `Gemfile.lock`) SHALL be
shown as one line, never diffed, and never cause a hold: path (and the old path of a rename), old and new size, lines
added and removed, how many changed lines touch a source, registry, remote, tarball, resolution or integrity field, and the hosts of every URL in the changed lines.

#### Scenario: SCN-VER-140 (+) A lock file is one line, never a diff
- **GIVEN** a unit whose diff changes `src/app/a.py` and `uv.lock`, the lock file by 30000 added lines
- **WHEN** the judge step lists the files of its diff
- **THEN** `uv.lock` is one entry whose text is `lock file uv.lock: <old> -> <new> bytes, +30000 -0 lines, 0 touch a
  source field, hosts: none (not diffed)`, none of its lines is shown, and `src/app/a.py` is diffed as usual

#### Scenario: SCN-VER-141 (+) A lock file of 300000 characters makes no hold
- **GIVEN** a unit whose diff is two small files and a `uv.lock` whose own diff is 300000 characters
- **WHEN** the judge step runs
- **THEN** the judge is called once, with one prompt that holds the lock file's line, and the round has no hold about
  the diff

#### Scenario: SCN-VER-142 (−) A file named like a lock file but not on the list is diffed
- **GIVEN** a unit whose diff adds `src/lock.py`, `docs/uv.lock.md` and `locks/notes.txt`
- **WHEN** the judge step lists the files of its diff
- **THEN** each is diffed in full, and none is shown as a lock file; the same holds for a source file renamed to
  `go.sum`, whose diff shows the rename and its code, and a lock file renamed to a lock file is one line that names the
  old path

#### Scenario: SCN-VER-144 (−) A deleted lock file is one line too
- **GIVEN** a unit whose diff deletes `Cargo.lock` of 6 bytes and 3 lines
- **WHEN** the judge step lists the files of its diff
- **THEN** it is one entry, `lock file Cargo.lock: 6 -> 0 bytes, +0 -3 lines, 0 touch a source field, hosts: none (not
  diffed)`; a `package-lock.json` whose `resolved` URL moves from `registry.npmjs.org` to another host shows the changed
  lines that touch a source field and both hosts

### Requirement: L4-VER-046 An accept of a hold on the judge's view is bound to what the judge did not see
The hash an accept of a `judge view:` hold is bound to SHALL cover the hold's text, the head blob id of every file the
hold covers and the full list of files the judge did not see; the hold's id stays the hash of its text. The accept is
void when that content changes, and the hold is asked again. The question SHALL list every unseen file (at most 100,
then a pointer to `verdict.json`, which lists them all); it covers the file mode too.

#### Scenario: SCN-VER-145 (−) An accept does not survive new content of the file it was given for
- **GIVEN** a round whose hold `judge view: the diff of `data/seed.json` is longer than one part …` a person accepted,
  and a next round whose `data/seed.json` has other content (the same hold text, so the same hold id)
- **WHEN** the next round settles its holds
- **THEN** the accept is not in force, the hold is unresolved and asked again, and an accept of unchanged content stays

#### Scenario: SCN-VER-146 (−) An accept does not survive a swapped unseen file the text does not name
- **GIVEN** an accepted hold that names five of seven unseen files (`(+2 more)`), and a next round in which one of the
  two files the text does not name is replaced by another
- **WHEN** the next round settles its holds
- **THEN** the hold text is the same, the accept is void, the hold is asked again, and its question lists all seven
  files, and for 500 files lists 100 and points at `verdict.json`

### Requirement: L4-VER-047 The file list of a part prompt is bounded and the content is read once
The file list of every part prompt SHALL hold at most 200 files and then `+K more files: see verification.md`, which
lists all of them; the room the list takes SHALL come out of the part's characters. The diff content of all files SHALL
come from one `git diff` split at its `diff --git` lines, and the text of files that land in no part SHALL not be kept.

#### Scenario: SCN-VER-147 (−) A diff of very many files has a bounded listing and a constant number of git diffs
- **GIVEN** a diff of 250 files in several parts
- **WHEN** the parts are listed and the prompts built
- **THEN** each prompt lists 200 files and `+50 more files: see verification.md`, `verification.md` lists all 250 by
  part, the packing left the list's characters free in every part, and listing the files ran a constant number of
  `git diff` calls

#### Scenario: SCN-VER-148 (+) A test lands with the code it imports
- **GIVEN** `src/app/report.py`, `src/app/models.py` of 100000 characters and `tests/test_api_flow.py`, which imports
  `app.report` and is named after no module
- **WHEN** the diff is packed in any input order
- **THEN** the test and `src/app/report.py` are in the same part, and a part that shows the code judges its criterion,
  whichever part holds the test

#### Scenario: SCN-VER-149 (−) A part that cannot see a test does not call it inadequate
- **GIVEN** part 1 calls the test T adequate and part 2, which does not show T, calls it inadequate with the reason
  `not in this part`
- **WHEN** the replies are merged
- **THEN** T is adequate, and a test inadequate for a reason of its own in any part that sees it stays inadequate
