## Context

Read at 0.4.59 (62188257):

- `specs/criteria.py`: `criterion_id` (36-38) hashes the framework, the capability, the requirement's name and the
  scenario's name; `spec_baseline` (332-341) reads the archived specs at the unit base from git for OpenSpec, or a Kiro
  follow-up's merged parent; `unchanged_ids` (344-349) keeps the ids the baseline holds with the same text after
  `normalise` (NFC, whitespace runs folded, case kept).
- `verifier/traceability.py` `trace_criteria` (190-251): a tracing test with no red, audit, human, chore, repair or
  generated proof gets `pass_to_pass` when its criterion is unchanged (218, 232), else it is ignored with `no proof that
  it discriminates (no red, audit or generated record)` (240-242). So a scenario restated word for word under a
  `MODIFIED` requirement already keeps its tests as evidence (L4-VER-009 names that case).
- `verifier/ladder.py` `traceability` (816-836) computes `archived = spec_baseline(...)` (821) and does not keep the
  unchanged ids. `_generate_step` (1248-1345): the gaps of `plan_generation` (1272-1275; only end-to-end tests close a
  gap, `ui_step.py:43-68`), `_test_blobs` (1230-1245, the test-to-file mapping), the waiver (1283-1294), the early
  return when every gap is waived (1295-1297), `hold_all` (1299-1301), the branch with no writer (1303-1306), the writer
  (1314-1340).
- `verifier/generate.py` `_discriminates` (182-222): a test that passes at the merge base is `non_discriminating`
  (200-203) and the head is not run; `ui_gap_finding` (70-84).
- `verifier/ui_step.py`: `_covers` (126-129) and `covered_by_step4` (132-145) refuse `pass_to_pass` as cover for the
  `not_testable` note of L4-VER-067; `lost_notes` (148-167); `unclosed_holds` (170-182); `ui_waivers` (221-278) reads
  the UI holds of a criterion from `question.raised{kind: verdict, criterion}` (235-248).
- `verifier/fixunit.py` (240-250): on a PASS with `fix_minor_findings`, a gap that is accepted, waived or noted is
  closed and gets no task.
- `verifier/report.py` `_generated_rows` (111-127); `evidence._generated` (168-176).

## Goals / Non-Goals

**Goals:** a UI criterion that the unit did not change, whose tests are the base's and pass, is not a step-5 gap that
can only end as a hold; the carry is listed where a reader looks; every doubt keeps today's path.

**Non-Goals:** fuzzy matching of scenario text; which criteria are UI-facing; the waiver; a browser check of a carried
criterion (D7); a criterion with any proof but `pass_to_pass`.

## Decisions

### D1. When a criterion is carried from the base

`carried_from_base(gaps, trace, unchanged, file_of, changed, rejected) -> dict[str, tuple[str, ...]]` in
`l4.verifier.ui_step` (pure): criterion id -> the sorted ids of its tracing tests, for each gap `C` with all of:

1. `C.id in unchanged`: the ids that `unchanged_ids(criteria, archived)` gives in step 4. `traceability` keeps them on
   the run (`_Run.unchanged: frozenset[str]`), from the same `archived` it traces with, so step 5 reads the one baseline
   step 4 read. Exact identity only.
2. `C`'s evidence in `result.trace` as step 5 starts has `state == "covered"`, no `held` reason and at least one
   tracing test; every tracing test has `status == "passed"`, `proof == "pass_to_pass"`, no `note`, `over_cap == 0`
   and `adequate`; every test listed as not evidence for `C` (`ignored`) is a passing candidate over the cap
   (`{t for t, _ in ignored} <= {t.id for t in capped}`). Any other proof means a task of the unit proved something
   for `C`, or a person or a chore wrote a test for it: not carried. This replaces "no task names the scenario", which
   has no reading for an OpenSpec unit (`implementer/tdd.py:433-437`: an OpenSpec task cites no criteria).
3. Every test of 2, listed or ignored, maps to a file (`file_of`: `file_of_test(wb, id)`, else `file_of_id(id,
   worktree_files(wb), changed)`, the mapping `_test_blobs` makes; split it out so both use it), and no such file is in
   `changed` (`unit_changed_files(wb.git, base_sha, head)`, which `_generate_step` already reads at 1272: what the unit
   changed since its merge base). A test whose file is not found is not carried.
4. `C` is not in `rejected`: `rejected_ui_criteria(events)` in `l4.verifier.ui_step` gives every criterion with a
   `human.verdict{decision: reject}` whose target is the criterion, or one of its UI holds (the targets of
   `question.raised{kind: verdict, criterion: C}` and `hold_id(ui_hold_text(C))`), consumed or not. A criterion that a
   reviewer ever rejected keeps step 5 and its hold, so a reject is never lost (`settle_holds` turns a reject into a
   finding only for a hold the round raises, `verdicts.py:300-305`).

### D2. Where in step 5

In `_generate_step`, right after `ui_waivers` (1283) and before `gap_findings` (1284): `carried =
carried_from_base(...)` over the gaps that are not waived. A waived criterion stays waived (its accept is in force);
a carried one is neither asked nor written for. `gaps` (1294) leaves out both. The early return (1295-1297) takes
"every gap waived or carried" and checks nothing out; its note counts both. The carry is decided before the branch with
no writer (1303-1306), since it needs none.

### D3. What a carry records

- `verify.generated{criterion, status: "carried", covered_by: [<ids>], attempts: 0}`, and an outcome
  `GeneratedOutcome(C, "carried", reason=..., covered_by=ids)` in `result.generated` (`GenStatus` gains `carried`);
  `verdict.json` stores it and `evidence._generated` restores it, so a reused round keeps it and decides nothing again.
- Its row in the generated UI tests table: status `carried`, reason `carried from the base: <ids> (the scenario and
  these tests are the base's, and they pass); a note, not a hold (L4-VER-086)`, at most three ids and `(+n more)`.
  `_generated_rows` writes this for a `carried` outcome instead of the `covered by step 4` text of L4-VER-067 that a set
  `covered_by` gives today.
- Step 5's note: `<n> carried from the base (L4-VER-086)`.
- Its minor gap finding stays: `ui_gap_finding(criterion, unproved, waived_by, carried=True)` says `No end-to-end test
  traces criterion C (…); it is unchanged on the base and its base tests pass, so step 5 generates none (L4-VER-086).`
- Closed: `unclosed_holds` raises no hold for it; the fix planner's closed set (`fixunit.py:242-246`) takes it, so no
  fix task is made for its gap; `lost_notes` treats it as a note with its `covered_by` (by D1 every tracing test is in
  `covered_by`, so it cannot fire; the rule is there so a later change cannot open a hole).
- Nothing is accepted or answered: no `human.verdict`, no waiver for a later round. Each fresh round decides again.

### D4. Why it is safe, and what is left

What step 5 could do for such a criterion: its scenario is the base's word for word (1), its tests are the base's own
files (3) and pass at the head (2). When the behaviour is in the base, a faithful browser test passes at the merge base
and step 5 returns `non_discriminating` (`generate.py:200-203`) without running the head. Every outcome is then a hold:
`non_discriminating`, `not_testable` (not a note: `pass_to_pass` is no cover for L4-VER-067), or a wrong test (it fails
at the base and the head, or errors). The hold asks a person to accept on a merge-base run that cannot show a break at
the head. In the evidence, every such hold was accepted.

What still stands before a PASS: the base's tests of the criterion pass at the head; the judge must pass the criterion,
and when it calls those tests inadequate the criterion is `needs_human`, asked through its own question (L4-VER-003);
step 3's e2e gate runs the whole e2e suite; the integrity checks are unchanged.

Fail safe: every doubt keeps today's path (a gap, the writer, a hold): a scenario with any changed word; a baseline that
cannot be read (`spec_baseline` gives nothing, so nothing is unchanged); a test the unit added or changed; a test whose
file is not found; a failing, skipped, unproven or over-cap test that does not pass; any proof but `pass_to_pass`; any
reject of the criterion or of its UI holds. A carry writes no answer, so it is never a person-only action, and it
widens no unfreeze.

Residual risk (named): a unit that breaks the browser side of a scenario it did not change, while the base's unit tests
of that scenario still pass and the judge passes it, is no longer asked about as a UI hold. Before, a person was asked,
on a merge-base run that could not show the break.

### D5. Follow-ups, Kiro and fix units

- A follow-up's family holds its merged parent's criteria. For OpenSpec they are unchanged once the parent's archive is
  in the follow-up's base (the archived specs then hold them); before that, nothing is unchanged and nothing is carried.
  For Kiro, `spec_baseline` reads the merged parent's criteria; a plain Kiro unit has no baseline and carries nothing.
- A fix unit is verified with its parent as one family, from the parent's merge base (`ladder.py:2072`, `family_of`), so
  "a file the unit did not change" means since the default branch, never since the fix unit's own start.

### D6. Upgrade

A new value of `verify.generated.status`; no new event or key; a 0.4.59 verdict never holds it. In the first fresh
round after the upgrade a criterion that qualifies is carried. An open UI hold question that an earlier round raised
for it is superseded by the round, because the round does not ask it (L4-OPS-014); an accepted one waives first, as
before; a rejected one stops the carry (D1.4). A reused round keeps its stored outcomes and holds. Ledgers written by
0.4.59 fold unchanged.

### D7. Considered and left for later: a pass-to-pass browser check

Step 5 could ask the writer for a test of a carried criterion and keep it when it passes at the merge base and at the
head, holding the criterion when it fails at the head. That would keep a browser check of the head. It costs a writer
call and two e2e runs per criterion in every fresh round (a follow-up that touched one web file makes every parent
criterion UI-facing), and a test that passes at both says little about the criterion. Later, if the residual risk of
D4 shows.

## Risks / Trade-offs

- The residual risk of D4.
- The decision rests on the trace step 4 made; a wrong `pass_to_pass` there (L4-VER-009) would carry here too. The
  baseline is read from git at the base (HB-3), never from the worktree.
- A reviewer who wants a browser check of an unchanged criterion gets none until the scenario's text changes or the
  criterion is rejected once.
