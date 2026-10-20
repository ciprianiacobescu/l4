## Context

`proposal.md` describes the incident. This change judges a criterion whose evidence the parts of a long diff split
between them on all of that evidence, in one follow-up judge call, and makes the verdict and the question say that the
evidence was split and what was done. It is built for 0.4.21 on top of the released 0.4.20 (da3e7c28).

Labels: [V] verified in the code or tests at da3e7c28 (file:line); [I] inferred; [U] unknown, not checked here. The
incident's own facts (about 141000 characters, two parts, one criterion `insufficient_evidence` in both, a person's
question) come from the report of 2026-10-20; this design does not re-read the consumer's repository or its replies.

How the incident happens in the code [V]:
- `MAX_PART_CHARS = 120_000` and `MAX_JUDGE_PARTS = 8` (`src/l4/verifier/diffparts.py:25-26`). `pack` (`:140-162`)
  sorts whole entries by `(group_key, path)`, a test with the code it is named after or imports (`_keys`, `:126-137`),
  and starts a new part when the next entry does not fit. 141000 characters of entries make two parts [I: the
  consumer's file sizes are not known here; two parts is what the report says].
- `pack` knows nothing of criteria. Code of one criterion in two modules whose name keys sort apart (for example
  `app/export.py` and `app/report.py`) lands in two parts whenever the cut falls between them.
- Each part prompt holds the rules of `_part_rules` (`src/l4/verifier/judge.py:381-395`): a criterion whose code is not
  in the part is `insufficient_evidence` with the reasoning `not in this part`. No rule covers a criterion whose code
  the part shows only in part; the judge answers `insufficient_evidence` with a reasoning of its own [I: the report].
- `_criteria` (`src/l4/verifier/judge_parts.py:25-32`) takes per criterion the first of `fail`, `pass`,
  `not_verifiable`, `insufficient_evidence` (`_ORDER`, `:16`) among the parts' answers. It reads only the verdict word,
  never `reasoning`. Two `insufficient_evidence` give `insufficient_evidence`.
- `aggregate_criterion` (`src/l4/verifier/aggregate.py:44-86`): a covered criterion (an adequate, passing tracing test)
  with a judge answer other than `pass` or `fail` is `needs_human` with the reason `the judge answered
  insufficient_evidence` (`:86`). `aggregate_unit` makes the round `NEEDS_HUMAN`, and `_criterion_question`
  (`src/l4/verifier/verdicts.py:507-542`) asks a person, with `Why: <reason>` (`:527`) and `Judge:
  insufficient_evidence` (`:528`). Nothing in the question says that the evidence was split.
- The pointers of the brief are right: the part rule is at `judge.py:387-389` and the merge at `judge_parts.py:16`.

## Goals / Non-goals

Goals: a criterion whose evidence lies in two or more parts is judged on all of it before a person is asked; the
verdict and the question say when the evidence was split and what was done; a criterion that truly lacks evidence
still ends `insufficient_evidence`, and a criterion any part failed still fails.

Non-goals:
- A new part layout. `pack`, the part count and size, the holds of L4-VER-043 and the accept binding of L4-VER-046
  stay as they are (D1).
- The feedback, accepted and satisfied items of a split diff. They have the same blind spot (an item whose code two
  parts each see in part can be answered false by both, with evidence of their own), but their merge is another rule
  (`_items`, `judge_parts.py:80-92`) with another outcome (a not-addressed feedback item fails the round). Listed in the
  follow-ups.
- A criterion the parts answered `not_verifiable`: that is a considered answer of a part that saw the code, not a
  missing view.
- A configuration key. The follow-up runs only where a person would otherwise be asked, and it is bounded (D4).

## D1. A follow-up call for a split criterion, not a new packing and not a new merge rule

Decision: after the parts are merged (L4-VER-042), each *split* criterion (D3) is judged once more, in a follow-up
call that shows only its files, whole, from every part (D2, D4, D5). The follow-up's verdict for it replaces the
merged `insufficient_evidence` (D7).

Alternatives:
- **(a) Pack the parts per criterion** (a criterion's code, tests and spec text in one part; split by criteria groups
  rather than by diff bytes). Rejected:
  - It needs the criterion-to-files map before any judge call, for every multi-part diff, and that map is a heuristic
    (D2): the parts' citations, its only judge-made source, do not exist yet.
  - Files that several criteria share (a model, an entry point, a configuration file) go into several parts, so the
    same diff needs more characters and more parts on every multi-part unit, and reaches the 8-part cap sooner, which
    is a `judge_view` hold that a person must accept (L4-VER-043).
  - It changes the part layout of L4-VER-041, the per-part criteria list of every part prompt, the hold views of
    L4-VER-046, and the scenarios SCN-VER-148, SCN-VER-161 and SCN-VER-165; and the feedback, accepted, satisfied and
    done-task blocks belong to no criterion, so they would need a home of their own.
  - A criterion whose own files are longer than one part is still split.
  - Its cost is paid by every multi-part unit; the follow-up's only by a round that would otherwise ask a person.
- **(c) A merge rule that combines the parts' `insufficient_evidence`.** Rejected. `_criteria` sees only verdict
  words, and the words of a part that saw half and of a part that saw nothing are the same. Two views that each could
  not confirm a criterion are not a confirmation: nobody judged how the halves work together. A rule that read the
  reasoning would put a free-text convention of the model on the path to a pass. A schema field (`partial: consistent
  so far`) would still not judge the whole, and changes `l4/judge-verdict@1`.
- **(d) A larger part.** The owner kept 120000 characters and 8 parts as constants (`plan-run-lessons` design §5,
  decision 3) [V]. Not reopened here; a larger part moves the boundary, it does not remove it.
- **(e) Order the entries by the task that wrote them** before the name key, so a task's files stay together. It
  would lower how often a criterion is split, but changes the packing of every multi-part diff and its scenarios.
  Listed in the follow-ups as a complement.

Why (b): it adds a call only to a round that has a split criterion, keeps every existing part, merge and hold rule,
and gives the judge, once, exactly what no part had: all of that criterion's files at once.

## D2. The files of a criterion

The files come from the harness's own records first. The judge's words only add files of the diff; they never remove
one and never add a file outside the diff. In this order, each source in the order given, without repeats:

1. **Cited.** For each part in order, the evidence references (`kind` `file` or `test`) of that part's verdict for the
   criterion: a reference names the diff path `P` when it equals `P` or starts with `P` and then `:` (a `path:line` or a
   `path::test`); the longest such `P` wins. Part replies are in memory at the merge [V: `replies`,
   `ladder.py:1162-1183`].
2. **Tracing tests.** The path of each test of the criterion's trace (`result.trace`, `CriterionEvidence.tests`, built
   by step 4 before step 9 [V: `apply_adequacy(result.trace, …)` reads it in step 9, `ladder.py:1195`]): the text of
   the test id before its first `::`, when that is a path of the diff. [I] Test ids of other runners than pytest may
   carry no path; they add nothing, and the other sources still apply.
3. **The code those tests import.** For each test file of source 2 that is an entry of the diff, the non-test entries
   whose `group_key` is a module that the test's added lines import (`_imported`), the rule by which `pack` puts a test
   next to its code (`diffparts.py:114-137`, L4-VER-041, review M2) [V].
4. **The files of its tasks.** The tasks whose red step added one of its tracing tests (`result.red_green`, test id ->
   task key, from `task.red_ok`, `_red_green`, `ladder.py:294-306`) [V], and the files that the harness commits of
   those tasks changed: the commits `base..head` whose `L4-Task` is one of those keys and whose `L4-Unit` is a unit of
   the family, read as `integrity.commits` and `integrity.tagged_files` read them (one `git log`, then one `git
   diff-tree --name-only -r -z -m --first-parent` per matching commit, `src/l4/verifier/integrity.py:601-624`) [V].
   [I] The test ids of `task.red_ok` and of the trace are the same strings (both come from the gate's report); task
   1.1 tests it on a real ledger and trace.

Only paths of the diff count (`e.paths[-1]` of an entry, a part's or an unseen one). The map is computed only when D3's
first three conditions hold for at least one criterion, so a round without one runs no extra git command.

Why these four: the tracing tests and their tasks' commits are what the harness proved about the criterion
(L4-VER-009, L4-IMP-003); the imports reuse the packing's own rule; the citations cover code that people wrote or that
no task commit touched. A `task.red_ok` carries `task`, `base`, `tests`, `frozen` and `notes`, no criteria [V:
`implementer/tdd.py:1311,1452`], so the link from a criterion to its tasks goes through its tests.

## D3. When a criterion is split

A criterion is split when all of these hold:
1. the round judged its diff in two or more parts;
2. its merged verdict is `insufficient_evidence` (no part answered `fail`, `pass` or `not_verifiable`);
3. its trace is `covered` and not held (`CriterionEvidence.state == "covered"`, `held == ""`): otherwise aggregation
   decides it without the judge (`uncovered: …`, the held reason, `aggregate.py:66-75`) [V], and a follow-up would be
   a call whose answer counts for nothing;
4. its files (D2) lie in two or more judged parts (a part cut to the cap counts as the part it is).

A criterion that fails 1 to 3 gets no follow-up and no note: its reason is today's. A criterion that meets 1 to 3 and
whose files lie in one part (or in no judged part) also gets neither: the part that showed its files judged it, so its
`insufficient_evidence` is real. That is the negative case the brief asks for (SCN-VER-191).

Alternatives:
- **Two or more parts answered `insufficient_evidence`** (the brief's first wording). In a two-part diff that is
  condition 2 alone, and it would make a follow-up for a criterion whose files all lie in one part, whose part already
  judged it. The words of the replies cannot tell the cases apart (D1 (c)); the files can.
- **The reasoning of the parts** (`not in this part` against anything else). Rejected for the same reason, and a
  model that phrases it differently would change the harness's path.

## D4. What a follow-up shows, the groups, and the bound

- **Room.** A follow-up holds whole entries in at most `MAX_PART_CHARS − parts.reserve` characters, the room of a part
  [V: `pack(entries, reserve=…)`, `diffparts.py:279-286`]. Its prompt has the same fixed sections as a part prompt or
  fewer (fewer criteria, no item blocks, D5), so it is never longer than the longest part prompt [I].
- **A criterion's files.** In D2's order, every file that still fits is taken; a file that does not fit is skipped and
  the next is tried. A file of a part cut to the cap and a file in no judged part are never shown (their text is cut or
  was not kept, and the `judge_view` hold of L4-VER-043 already asks a person about it). The files not taken are the
  criterion's *not shown* files. When the files taken lie in one part only, the criterion gets no follow-up
  (`no_fit`, D8).
- **Groups.** The split criteria in the unit's criteria order. A criterion joins the first group (in the order the
  groups were made) whose files together with its own still fit; else it starts a new group. A group's files are shown
  in the order the parts hold them (part, then the packing's order), so a test still sits next to its code.
- **Bound.** At most as many follow-up calls as the round judged parts (`len(parts.parts)`). A criterion that would
  need a group past the bound gets no follow-up (`no_call_left`, D8). A round therefore makes at most twice as many
  judge prompts as parts, at most 16.

Alternatives:
- **Show all of a criterion's files or none** (fit-or-skip). Simpler, but one large file of a task (a task that also
  touched a big unrelated file) would cancel the follow-up although the files that matter fit. The order of D2 puts
  the files the judge asked for and the tests first.
- **One follow-up call per round.** Cheaper, but a diff of three or more parts with two split criteria in different
  areas would still ask a person about one of them. The bound by the part count keeps the cost in proportion to the
  diff.
- **One call per criterion.** Repeats the spec, the criteria list and the gate report for each; grouping costs one
  loop.

## D5. The follow-up prompt

`build_judge_prompt` gains `followup: FollowUpView | None` (exclusive with `part`). A follow-up prompt is the round's
prompt (the same spec sources, gate report, conventions, owner changes, round outputs and implementer notes) with:
- the criteria block holding the group's criteria only;
- no feedback, accepted, satisfied or done-tasks block (`feedback=()`, `accepted=()`, `satisfied=()`, `tasks=()`), so
  the reply has no item to answer and L4-VER-017's second call is never asked for an item;
- the diff section headed `## Diff (base...head), follow-up K of M`, then these rules, then the file list, then the
  group's files:

```
This change's diff is longer than one prompt holds and was judged in N parts. No part could judge the criteria listed
above alone: their files lie in parts P. This prompt shows those files together, whole. Judge every criterion listed
above on what this prompt and the gate report show:
- A file listed as not shown is in the change but not in this prompt: never answer fail for what it might hold;
answer insufficient_evidence when what is shown is not enough.
- A fail must cite code shown in this prompt.
- A test that is not shown in this prompt: leave it out of test_adequacy.
```

  `P` is the parts the group's files come from, as `1 and 2` or `1, 2 and 4`. The file list is a `<l4:data kind="diff
  parts">` block: `part K: <path> (<chars> characters)` for each file shown, then `not shown: <path> (part K, <chars>
  characters)` or `not shown: <path> (no part, <chars> characters)` for each not-shown file of the group's criteria,
  with the caps of L4-VER-047 (200 lines, paths cut to 200 characters).

The follow-up is asked through `_ask_judges`, like a part: the same judge chain, the same independence check, the same
cost and call accounting, and its prompt is published like a part's [V: `ladder.py:1327-1392`].

## D6. The part prompt names what it saw; `judge@12`

`_part_rules` gains one rule, after the rule of a criterion not in the part:

```
- A criterion whose code this part shows only in part: judge it when what is shown is enough; otherwise answer
insufficient_evidence and cite in its evidence each file of this part that holds some of its code.
```

It feeds source 1 of D2. It names code only, never tests: review M2 kept every part rule free of a rule that sends a
test elsewhere, and `tests/unit/verifier/test_prompt.py:199-203` asserts that no part rule says `or test` [V]; the
tests of a criterion come from its trace (source 2).

`PROMPT_VERSION` becomes 12 (`# 12: the follow-up prompt and the rule of a criterion shown in part`), as 10 was for
the parts [V: `judge.py:36-42`]. The system text (`SYSTEM`) does not change, so its hash in
`src/l4/templates.lock.json` stays; only the lock's `version` becomes 12, regenerated with `python -m
l4.templatelock --write` [V: `templatelock.py:33`, a version that differs from the lock fails
`tests/unit/test_template_lock.py`]. A diff within one part gets no part rule and no follow-up, so its prompt and
its hash stay byte for byte (`SINGLE_SHA`, `test_prompt.py:149-157`) [V].

Alternative: no change to the part prompt (keep `judge@11`). The harness sources 2 to 4 would still select the files,
but code that people wrote, or that no task commit touched, would be found only through imports. A new prompt shape
(the follow-up section) is a template change either way, so the version moves.

## D7. Merging a follow-up, and what is never re-judged

- `apply_followups(merged, answered)` (new, `judge_followup.py`): for each group whose reply is valid, the reply's
  verdict for each of the group's criteria (`pick_verdicts` of the reply) replaces the merged verdict of that
  criterion, at its place in `criteria`. A verdict for an id outside the group is ignored. A group criterion the reply
  leaves out keeps the merged verdict (`not_answered`). `test_adequacy` is `_adequacy([merged, *replies])` and
  `findings` is `_findings([merged, *replies])`, the rules of L4-VER-042 [V: `judge_parts.py:35-66`].
  `riskiest_assumptions`, `feedback`, `accepted` and `satisfied` stay the merged ones. `merge_part_verdicts` is not
  changed, so SCN-VER-162 to SCN-VER-164 and SCN-VER-149 keep their result.
- Any verdict of the follow-up counts as a part's would: a `pass` with a covered criterion passes it; a `fail` goes
  through the counterexample rule (`_counterexample`, `ladder.py:1395-1406`; unexecuted, so `needs_human`, never a
  FAIL of the unit, P7) [V]; `insufficient_evidence` or `not_verifiable` stays `needs_human`.
- Never re-judged: a criterion that any part answered `fail`, `pass` or `not_verifiable` (D3 condition 2). A `fail` of
  any part therefore still wins (SCN-VER-163, SCN-VER-196).
- A follow-up that gives no valid verdict (`schema_invalid` or `timeout` after its repair or retry, `model_mismatch`
  or `error` with no next judge, or a usage limit with no next judge) keeps the merged verdict of its criteria
  (`no_answer` with that status, `limit` for a usage limit). Unlike a part (SCN-VER-166, `ladder.py:1169-1172`), it
  does not discard the round's judge verdict, raises no `RoleUnavailable`, and adds no hold: the criterion's own
  question says it (D8).
- The counterexamples, the unknown-criteria finding, `judge_findings`, `apply_adequacy` and the S1 calibration rows
  read the verdict after the follow-ups (`run.judged`), as they read the merged one today [V: `ladder.py:1183-1197`,
  `_calibrate` `:1064`].

Alternative for a discarded follow-up: a hold `the judge's reply was discarded (follow-up K of M, …)`, as for a part.
Rejected: the criterion is already `needs_human` and asked about; a hold would ask the person a second question about
the same thing.

## D8. The texts, the records, a resumed round

- **The note.** For each criterion that meets D3, `judge_split[cid]` records `parts` (the judged parts its files lie
  in), `outcome`, `followup` (K or null), `files` (the number shown), `not_shown` (paths), `answer` (the follow-up's
  verdict word or null) and `status` (null, or the status of a follow-up with no answer). `split_note(record)` gives,
  with `<parts>` as `1 and 2` or `1, 2 and 4`:
  - `answered`: `its evidence was split over parts <parts> of the diff: follow-up call <K> judged its <n> files of
    those parts together and answered <verdict>`, followed by ` (<m> not shown: <p1>, <p2>, <p3>, +<r> more)` when
    files were not shown (at most three paths named);
  - `not_answered`: `its evidence was split over parts <parts> of the diff: follow-up call <K> judged its files of
    those parts together but gave no verdict for it, so the parts' verdict stands`;
  - `no_answer`: `its evidence was split over parts <parts> of the diff: follow-up call <K> gave no usable answer
    (<status>), so the parts' verdict stands`;
  - `no_fit`: `its evidence was split over parts <parts> of the diff: no follow-up call was made, because its files of
    those parts do not fit in one part together`;
  - `no_call_left`: `its evidence was split over parts <parts> of the diff: no follow-up call was made, because the
    round's <N> follow-up calls were used`.
- **Where it shows.** `aggregate_criterion(..., split: str = "")` appends `; <note>` to the reason of an outcome that
  rests on the judge's verdict: `pass` (`the judge passed it and a discriminating test passes; its evidence was split
  …`), a judge `fail` counted as insufficient, and `the judge answered <word>`. Outcomes decided before the judge (a
  failing tracing test, a person's verdict, uncovered, held) are unchanged. The reason is the question's `Why:` line
  [V: `verdicts.py:527`] and the criteria table's last column of `verification.md` [V: `report.py:134`]. The question's
  identity is the criterion's text hash, not the reason [I: `text_sha256(c)`, `ladder.py:840`], so a changed reason
  asks no new question.
- **`verification.md`.** The judge line says `judged in 2 parts and 1 follow-up` (`follow-ups` for more than one);
  under the part rows, one row per follow-up call: `  - follow-up K: <ids>; files of parts <parts>: <n> file(s), <c>
  characters, profile <p>, reply <reply or status>`.
- **`verdict.json`.** `judge_followups`: one row per call `{followup, criteria, parts, files, chars, not_shown,
  profile, calls, reply, status, prompt_sha256}`; `judge_split`: the records above. `prompt_sha256` of the round is
  the hash of the part prompts' hashes and then the follow-up prompts' hashes, joined by a newline (unchanged when
  there is no follow-up) [V: `ladder.py:1159-1160`]. `judge_calls` and `cost_usd` count the follow-up calls.
  `judge_reply` stays the worst reply of the parts (`ladder.py:1181-1182`): a follow-up's reply is in its row.
- **Ledger.** A follow-up's `verify.judge` carries `followup: K`, `followups: M` and `criteria: [ids]` in place of
  `part` and `parts` [V: `ladder.py:1360-1365`].
- **A resumed round** makes no judge call (`_NoJudge`, `ladder.py:1416-1420`) [V]; `evidence.py` copies
  `judge_followups` and `judge_split` from the previous `verdict.json` beside `judge_parts` (`evidence.py:184`) [V],
  so `_finalize` builds the same notes.

## D9. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`: L4-VER-056 to L4-VER-058 after L4-VER-047; SCN-VER-190 to SCN-VER-203 after SCN-VER-157 (before
  `## MODIFIED Requirements`); the step 9 row of §10.2 names the follow-up; L4-VER-041 names the new part rule;
  L4-VER-042 says that L4-VER-057 runs after the merge; L4-VER-018's template sentence says `judge@12`; SCN-VER-161's
  template is `judge@12`; change-table row 59. This branch carries the SPEC text; the implementation changes it only
  to match the code, with the orchestrator.
- `docs/runbook.md`, the verdict questions (§7.1): one bullet after the `judge view: …` bullet, on a criterion
  question whose `Why:` says `its evidence was split over parts`.
- `CHANGELOG.md`: `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)`, with `### Changed` and `### Fixed` (the
  lines are in `tasks.md`).

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.verifier.judge_followup`:
  - `@dataclass(frozen=True) class Split: criterion: str; parts: tuple[int, ...]; files: tuple[str, ...]` (D2's
    files in D2's order) — the criteria of D3.
  - `criterion_files(cid, *, replies: Sequence[JudgeVerdict], evidence: CriterionEvidence | None, parts: DiffParts,
    red_green: Mapping[str, str], task_files: Mapping[str, frozenset[str]]) -> tuple[str, ...]` (D2; pure).
  - `task_files(git, base: str, head: str, units: Collection[str], tasks: Collection[str]) -> dict[str,
    frozenset[str]]` (D2 source 4; task key -> paths).
  - `find_splits(criteria, merged: JudgeVerdict, trace, parts: DiffParts, files_of: Callable[[str], tuple[str, ...]])
    -> list[Split]` (D3).
  - `@dataclass(frozen=True) class Group: index: int; criteria: tuple[str, ...]; entries: tuple[DiffEntry, ...];
    parts: tuple[int, ...]; not_shown: tuple[tuple[str, int, int], ...]` (path, part number or 0, characters).
  - `plan_followups(splits, parts: DiffParts) -> tuple[list[Group], dict[str, dict]]` (D4; the groups, and the
    `judge_split` records of `no_fit` and `no_call_left`).
  - `apply_followups(merged: JudgeVerdict, answered: Sequence[tuple[Sequence[str], JudgeVerdict]]) -> JudgeVerdict`
    (D7).
  - `split_note(record: Mapping[str, Any] | None) -> str` (D8; `""` for None).
- `l4.verifier.judge`: `@dataclass(frozen=True) class FollowUpView: index: int; count: int; parts: int; from_parts:
  tuple[int, ...]; listing: tuple[tuple[int, str, int], ...]; not_shown: tuple[tuple[str, int, int], ...]; more: int =
  0`; `build_judge_prompt(..., followup: FollowUpView | None = None)`; `PROMPT_VERSION = 12`.
- `l4.verifier.aggregate.aggregate_criterion(..., split: str = "")`.
- `VerifyResult.judge_followups: list[dict[str, Any]]`, `VerifyResult.judge_split: dict[str, dict[str, Any]]`.
- Ledger: `verify.judge` + `followup?`, `followups?`, `criteria?`.
- Texts: D5, D6 and D8, word for word.

## Collisions

- Changes drafted at the same time take other id ranges (this change: L4-VER-056 to L4-VER-058, SCN-VER-190 to
  SCN-VER-203). [U] Whether one of them also edits `_part_rules`, `build_judge_prompt` or `PROMPT_VERSION`: two
  changes that bump the judge template must agree on one number at merge (the later one takes 13).
- Change-table row 59 and `## 0.4.21 (unreleased)`: another branch that lands first may take row 59 and create the
  heading; whoever merges second renumbers the row and merges the lists under the same subheadings.
- `tests/unit/docs/test_plan_run_lessons_docs.py:25,55` look for `judge@11` in SPEC and CHANGELOG; SPEC keeps the
  words `judge@11` since L4-KSP-014, and the 0.4.15-era CHANGELOG line is not touched, so they keep passing [V: the
  file].

## Risks

- A follow-up `pass` rests on the files the harness chose. A criterion whose code lies in a file no source names is
  judged without it; the judge is told the follow-up shows only those files and that a file not shown must not fail a
  criterion, but it may pass a criterion on what it sees. The same holds for a part today (a part that sees the code
  passes it, whatever another part holds, SCN-VER-162), and a pass still needs a discriminating, adequate tracing test
  that passes (`aggregate.py:66-80`).
- Cost: at most as many extra calls as parts, in a round that has a split criterion. A round of 8 parts with split
  criteria in 8 separate areas makes 16 calls [I: unlikely; most diffs are 2 or 3 parts].
- Determinism: the follow-ups are a function of the parts (deterministic), the trace, `red_green` and the commits
  (deterministic), and the parts' replies (the verdict words and citations). The same replies give the same calls;
  every prompt's hash is recorded.
- A citation that names a file of the diff that has nothing to do with the criterion only adds a file to the
  follow-up. It cannot add a file outside the diff and cannot remove one.

## Out of scope / follow-ups

- The same follow-up for feedback, accepted and satisfied items whose code two parts each see in part (Non-goals).
- Ordering the entries by task before the name key (D1 (e)), to make splits rarer.
- A criterion that no part answered at all (`the judge gave no verdict for this criterion`).

## Open questions (each with the recommended answer)

1. Which option? Recommended and drafted: (b), a follow-up call (D1).
2. What makes a criterion split: the replies or the files? Recommended: the files, with the merged verdict as the
   gate (D3).
3. A configuration key to turn the follow-up off or to bound it? Recommended: no key; the bound is the part count
   (D4).
4. A discarded follow-up: a hold or only the note? Recommended: only the note (D7).
5. Does the part prompt change (and the template move to `judge@12`)? Recommended: yes, one rule (D6).
6. Should the items (feedback, accepted, satisfied) get the same follow-up in this change? Recommended: no, a separate
   change (Non-goals).
