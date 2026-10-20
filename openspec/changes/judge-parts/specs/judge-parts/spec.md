## Purpose

A criterion whose code and tests the parts of a long diff split between them is judged on all of that evidence, in
one follow-up judge call, before a person is asked about it. The verdict and the question say that the evidence was
split and what was done. A criterion that truly lacks evidence still ends `insufficient_evidence`, and a criterion
that any part failed still fails.

## ADDED Requirements

### Requirement: L4-VER-056 A criterion whose evidence the parts split is found from the harness's records
After the replies of a diff judged in parts are merged (L4-VER-042), a criterion SHALL be *split* when the round judged
two or more parts, its merged verdict is `insufficient_evidence` (no part answered `fail`, `pass` or `not_verifiable`),
no person has given a verdict for it, its trace is `covered` and not held once the parts' test adequacy is applied to it
(a criterion whose only passing tracing tests the parts called inadequate is not covered), and its files lie in two or
more judged parts (a part cut to the cap counts as the part it is). Its files SHALL be the paths of the diff named, in
this order and without repeats, by: the evidence references (`file` or `test`) of each part's verdict for it, in part
order (a reference names the longest diff path it equals or that it starts with followed by `:`); the file of each of
its tracing test ids as `file_of_test` resolves it, when it is a path of the diff (a pytest id is `classname::name` with
a dotted classname, as `packages.api.tests.test_x::test_y`, never a path); the non-test entries whose name key is a
module those test files' added lines import (the packing rule of L4-VER-041); and the files that the harness commits
`base..head` changed of the tasks whose `task.red_ok` proof for the criterion lists tests (`task.red_ok.criteria`;
`L4-Task` one of those tasks, `L4-Unit` a unit of the family). A path outside the diff, and a path that `file_kind`
classifies as exempt (a harness, spec or unit-folder path, the rule by which `_changed_code` leaves such files out),
MUST NOT be a file of a criterion, so a task's tick of `tasks.md` never makes a criterion split. The files SHALL be
computed only when a criterion meets the first four conditions, so a round without one runs no extra git command. A
criterion whose files lie in one part, or in no judged part, MUST NOT be split: its `insufficient_evidence` stands and
its reason is unchanged. Each part prompt SHALL hold the rule `A criterion whose code this part shows only in part:
judge it when what is shown is enough; otherwise answer insufficient_evidence and cite in its evidence each file of this
part that holds some of its code.`, and the judge template SHALL be `judge@12`, the number that the change
`verifier-cap` also gives the template in the same release (0.4.21); the template lock is regenerated after each of the
two changes. The user text of a diff that fits in one prompt is unchanged by this change.

#### Scenario: SCN-VER-190 (+) A criterion split over two parts is passed by one follow-up call
- **GIVEN** a unit whose diff is 141000 characters: `src/app/export.py` (60000), `tests/test_export.py` (40000),
  `src/app/report.py` (25000) and `tests/test_report.py` (16000), packed into part 1 (`src/app/export.py`,
  `tests/test_export.py`) and part 2 (`src/app/report.py`, `tests/test_report.py`); criterion C-1 traced and covered by
  `tests.test_report::test_header`, which task 1.2's red step added and whose commits change `src/app/export.py` and
  `src/app/report.py`; and both parts answering `insufficient_evidence` for C-1, part 1 citing `src/app/export.py:12`
- **WHEN** the judge step runs
- **THEN** a third judge call, follow-up 1 of 1, lists C-1 alone and shows `src/app/export.py`, `src/app/report.py` and
  `tests/test_report.py` whole; it answers `pass`; C-1 is `pass` with the reason `the judge passed it and a
  discriminating test passes; its evidence was split over parts 1 and 2 of the diff: follow-up call 1 judged its 3 files
  of those parts together and answered pass`; no verdict question is asked for C-1; and `judge_calls` is 3

#### Scenario: SCN-VER-191 (−) A criterion whose files lie in one part keeps insufficient_evidence
- **GIVEN** the diff of SCN-VER-190 and criterion C-2, covered by `tests.test_export::test_csv`, which task 1.1's red
  step added and whose commits change `src/app/export.py`, `tests/test_export.py` and the unit folder's `tasks.md` (a
  tick; part 2 holds it); part 1 answers `insufficient_evidence` for C-2 and part 2 answers `insufficient_evidence` with
  the reasoning `not in this part`; and, in turn, a diff within one part whose one reply answers `insufficient_evidence`
  for C-2
- **WHEN** the judge step runs and the round is aggregated
- **THEN** no follow-up call is made (two calls, then one), `tasks.md` is not a file of C-2 (a unit-folder path is
  exempt), C-2 is `needs_human` with the reason `the judge answered insufficient_evidence` and nothing after it, and
  `judge_split` has no entry for C-2

#### Scenario: SCN-VER-192 (−) A criterion the judge cannot decide gets no follow-up
- **GIVEN** the diff of SCN-VER-190, and in turn criterion C-3 with no tracing test (uncovered), criterion C-4 whose
  trace is held by a failed audit test, criterion C-5 with a person's verdict, and criterion C-6 whose only passing
  tracing test the parts' `test_adequacy` called inadequate, each with code in both parts and `insufficient_evidence`
  from both parts
- **WHEN** the judge step runs
- **THEN** no follow-up call is made, and C-3 is `needs_human` with `uncovered: no adequate discriminating test traces
  it` and C-4 with its held reason, C-5 has the person's verdict and C-6 is `needs_human` as an uncovered criterion, all
  without a note

#### Scenario: SCN-VER-193 (+) The files of a criterion come from the harness's records and the diff only
- **GIVEN** a split criterion whose part 1 cites `src/app/export.py:40` and `docs/old.md:3` (not in the diff), whose
  tracing tests are `tests.test_report::test_header` (a dotted pytest classname, which `file_of_test` resolves to
  `tests/test_report.py`) and `test_header` (an id that resolves to no file), whose test file imports `app.report` and
  `app.util` (`src/app/util.py` is not in the diff), and whose task's commits change `src/app/report.py`,
  `src/app/format.py`, the unit's `.l4/ledger/r1.jsonl` and the unit folder's `tasks.md`
- **WHEN** its files are computed
- **THEN** they are, in order, `src/app/export.py`, `tests/test_report.py`, `src/app/report.py` and `src/app/format.py`;
  `docs/old.md`, `src/app/util.py`, the ledger file and `tasks.md` are not among them; and a round whose merged verdicts
  have no `insufficient_evidence` for a covered criterion runs no `git log` for task files

#### Scenario: SCN-VER-194 (+) The prompts of the parts and of a follow-up
- **GIVEN** the round of SCN-VER-190, with one taken feedback item, one accepted finding, one task ticked as already
  satisfied and done tasks
- **WHEN** the prompts are built
- **THEN** each part prompt holds the rule of a criterion shown in part; the follow-up prompt's diff section is headed
  `## Diff (base...head), follow-up 1 of 1`, its rules say `was judged in 2 parts` and `their files lie in parts 1 and
  2`, its file list has every file of the diff, `shown: src/app/export.py (part 1, 60000 characters)` and, for a file
  left out of the group, `not shown: <path> (part K, <chars> characters)`, and no line says or suggests that the prompt
  shows the whole change; its criteria block lists only C-1, and it has no feedback, accepted, satisfied or done-tasks
  block; every prompt's template is `judge@12`, and the user text of a diff that fits in one prompt is unchanged

### Requirement: L4-VER-057 A split criterion is judged once more on all of its files, never making a round worse
The judge step SHALL make follow-up calls for the split criteria (L4-VER-056) after the merge and before anything reads
the verdict. A follow-up SHALL hold whole entries in at most the characters of a part (120000 less the room of the file
list). For each split criterion, its files SHALL be taken in their order while they fit, a file that does not fit
skipped; a file of a part cut to the cap and a file in no judged part MUST NOT be shown. A criterion whose taken files
lie in one part SHALL get no follow-up. The split criteria SHALL be grouped in the unit's criteria order on the files of
the first three sources of L4-VER-056 (cited, tracing tests, imported code), each joining the first group whose files
together with its own still fit, else starting a new one; the room that remains in each group SHALL then be filled with
the files of the tasks' commits, in the same order, each while it fits; a group's files SHALL be shown in the order the
parts hold them; a round SHALL make at most as many follow-up calls as it judged parts. A follow-up prompt SHALL be the
round's prompt with only the group's criteria, no feedback, accepted, satisfied or done-tasks block, and a diff section
headed `## Diff (base...head), follow-up K of M` with the rules of a follow-up (judge each listed criterion on what is
shown; a file marked not shown never makes a `fail`, and is a reason for `insufficient_evidence` when what is shown is
not enough; a `fail` cites code shown; a test not shown is left out of `test_adequacy`) and a file list of every file of
the diff, each marked `shown: <path> (part K, <chars> characters)` or `not shown: <path> (part K, <chars> characters)`
(`(no part, …)` for a file in no judged part). The wording of the follow-up prompt MUST NOT say or suggest that it shows
the whole change. A follow-up SHALL be asked through the same judge chain as a part. Its verdict for a criterion of its
group SHALL replace the merged verdict; a verdict for another id MUST be ignored; a group criterion it leaves out keeps
the merged verdict. A follow-up changes only its own group: of its `test_adequacy` entries and findings only those whose
`criterion` is in the group count (an entry with an empty criterion is dropped), and they are merged as a part's
(L4-VER-042). A criterion that any part answered `fail`, `pass` or `not_verifiable`, or that has a person's verdict,
MUST NOT be re-judged. A follow-up `fail` SHALL go through the counterexample rule like any judge `fail`, so it never
fails the unit alone. A follow-up that gives no valid verdict (schema break after the repair or retry, timeout, model
mismatch, error or usage limit with no next judge) SHALL keep the merged verdict of its criteria and MUST NOT discard
the round's judge verdict, raise a hold or stop the round.

#### Scenario: SCN-VER-195 (−) A split criterion the follow-up cannot confirm stays a person's question
- **GIVEN** the round of SCN-VER-190 whose follow-up answers `insufficient_evidence` for C-1
- **WHEN** the round is aggregated and the questions are written
- **THEN** C-1 is `needs_human`, and its question's `Why:` line reads `the judge answered insufficient_evidence; its
  evidence was split over parts 1 and 2 of the diff: follow-up call 1 judged its 3 files of those parts together and
  answered insufficient_evidence`

#### Scenario: SCN-VER-196 (−) A fail in any part is never re-judged
- **GIVEN** the diff of SCN-VER-190 where part 1 answers `fail` for C-1 with a counterexample and part 2
  `insufficient_evidence`; and in turn part 1 answering `not_verifiable` and part 2 `insufficient_evidence`
- **WHEN** the judge step runs
- **THEN** no follow-up call is made; C-1 is `needs_human` with `judge fail counted as insufficient_evidence:
  counterexample unexecuted (…)` in the first case and `the judge answered not_verifiable` in the second, without a note

#### Scenario: SCN-VER-197 (+) Split criteria share a follow-up when their files fit, and the calls are bounded
- **GIVEN** a diff in three parts with split criteria C-1, C-2 and C-3 in that order, whose files are 50000, 40000 and
  60000 characters with no file in common; and in turn a diff in two parts with three split criteria whose files are
  70000 characters each
- **WHEN** the judge step plans its follow-ups
- **THEN** the first round makes two follow-up calls, the first with C-1 and C-2 and the second with C-3; the second
  round makes two follow-up calls, and the third criterion gets none, with the note `… no follow-up call was made,
  because the round's 2 follow-up calls were used`

#### Scenario: SCN-VER-198 (−) A file longer than one part is never shown, and files that do not fit make no call
- **GIVEN** a split criterion whose files are `data/seed.json` (300000 characters, a part of its own, cut) and
  `src/app/seed.py` (part 1); and in turn a split criterion whose files are `src/app/a.py` (80000, part 1) and
  `src/app/b.py` (70000, part 2)
- **WHEN** the judge step plans its follow-ups
- **THEN** neither gets a follow-up call; each reason ends `… no follow-up call was made, because its files of those
  parts do not fit in one part together`; and the `judge view:` hold of `data/seed.json` (L4-VER-043) stays

#### Scenario: SCN-VER-199 (−) A follow-up with no usable answer keeps the parts' verdict and the round's
- **GIVEN** the round of SCN-VER-190 whose follow-up reply breaks the schema twice; and in turn a follow-up that hits a
  usage limit with no next judge
- **WHEN** the judge step ends
- **THEN** the round keeps its merged judge verdict, has no hold `the judge's reply was discarded`, and goes on; C-1
  stays `insufficient_evidence` and its reason ends `follow-up call 1 gave no usable answer (schema_invalid), so the
  parts' verdict stands`, or `(limit)` in the second case

#### Scenario: SCN-VER-200 (−) A follow-up fail never fails the unit alone
- **GIVEN** the round of SCN-VER-190 whose follow-up answers `fail` for C-1 with a counterexample
- **WHEN** the round is aggregated
- **THEN** C-1 is `needs_human` with `judge fail counted as insufficient_evidence: counterexample unexecuted (…)` and
  the note `… answered fail`, and the unit's verdict is `NEEDS_HUMAN`, not `FAIL`

#### Scenario: SCN-VER-201 (−) A follow-up changes only the criteria it was asked about
- **GIVEN** a follow-up for C-1 and C-2 whose reply answers `pass` for C-1, leaves out C-2, and answers `fail` for C-9,
  which part 1 passed
- **WHEN** the reply is applied
- **THEN** C-1 is `pass`, C-2 keeps `insufficient_evidence` with the note `follow-up call 1 judged its files of those
  parts together but gave no verdict for it, so the parts' verdict stands`, and C-9 keeps the `pass` of part 1; and, in
  turn, for a follow-up for C-1 alone whose reply marks a test inadequate with no criterion and a test of C-2
  inadequate, the merged `test_adequacy` holds neither entry and C-2's verdict is the parts' (a follow-up changes only
  its own group)

### Requirement: L4-VER-058 The verdict and the question say that the evidence was split and what was done For each
split criterion, the round SHALL record in `verdict.json` `judge_split` its parts, its outcome (`answered`,
`not_answered`, `no_answer`, `no_fit` or `no_call_left`), its follow-up, the number of files shown, the files not shown,
the follow-up's answer and the status of a follow-up with no answer. The reason of its outcome, when the outcome rests
on the judge's verdict, SHALL end with `; ` and a note that starts `its evidence was split over parts <parts> of the
diff: ` (`<parts>` as `1 and 2` or `1, 2 and 4`) and then says what was done: `follow-up call <K> judged its <n> files
of those parts together and answered <verdict>` (with ` (<m> not shown: …)` naming at most three paths when files were
not shown), `follow-up call <K> judged its files of those parts together but gave no verdict for it, so the parts'
verdict stands`, `follow-up call <K> gave no usable answer (<status>), so the parts' verdict stands`, `no follow-up call
was made, because its files of those parts do not fit in one part together`, or `no follow-up call was made, because the
round's <N> follow-up calls were used`. That reason SHALL be the verdict question's `Why:` line and the reason in the
criteria table of `verification.md`. `verification.md` SHALL say `judged in <N> parts and <M> follow-up` (`follow-ups`
for more than one) and list each follow-up call (`follow-up K: <ids>; files of parts <parts>: <n> file(s), <c>
characters, profile <p>, reply <reply>`). `verdict.json` SHALL list `judge_followups`, one row per call. A follow-up's
`verify.judge` SHALL carry `followup`, `followups` and `criteria`. The round's `prompt_sha256` SHALL hash the part
prompts' hashes and then the follow-up prompts' hashes; `judge_calls` and the cost SHALL count the follow-up calls;
`judge_reply` SHALL stay the worst reply of the parts, and `judge_replies` SHALL count every call's reply, follow-ups
included. `verdict.json` `judge_verdict` SHALL be the verdict after the follow-ups. The round's `judge_profile`,
`judge_model` and `independence` SHALL stay those of the judge of the parts; the profile of a follow-up is in its
`judge_followups` row and its `verify.judge` event. A resumed round MUST make no follow-up call and SHALL keep the
records, the notes and the follow-ups' verdicts of the round it reuses.

#### Scenario: SCN-VER-202 (+) The records name each follow-up
- **GIVEN** the round of SCN-VER-190
- **WHEN** its evidence is written
- **THEN** `verification.md` says `judged in 2 parts and 1 follow-up` and lists `  - follow-up 1: C-1; files of parts 1
  and 2: 3 file(s), 101000 characters, profile <judge>, reply valid`; `verdict.json` has one `judge_followups` row with
  `followup` 1, `criteria` [C-1] and `parts` [1, 2], and `judge_split` C-1 with `outcome` `answered` and `answer`
  `pass`; the follow-up's `verify.judge` has `followup` 1, `followups` 1, `criteria` [C-1] and no `part`;
  `prompt_sha256` is the hash of the three prompt hashes joined by newlines; `judge_reply` is the worst reply of the two
  parts; and `judge_profile`, `judge_model` and `independence` of the round are those of the judge of the parts

#### Scenario: SCN-VER-203 (+) A resumed round keeps the notes and makes no call
- **GIVEN** the round of SCN-VER-195 ended `NEEDS_HUMAN`; and in turn the round of SCN-VER-190, whose follow-up passed
  C-1, ended `NEEDS_HUMAN` because another criterion C-2 is uncovered; each followed by a next round on the same subject
  that resumes at aggregation
- **WHEN** the next round runs
- **THEN** no judge call is made, `judge_followups` and `judge_split` are the previous round's, and C-1's reason ends
  with the same note; in the second case `judge_verdict` of the previous `verdict.json` holds the follow-up's `pass` for
  C-1, and C-1 is `pass` again in the resumed round, not `needs_human`
