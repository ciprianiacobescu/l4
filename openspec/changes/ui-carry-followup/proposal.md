## Why

Step 5 raises a UI hold for every UI-facing criterion that has no end-to-end test, and `ui_facing_criteria` returns every
criterion of the family as soon as the unit changes one file under `ui_paths` (`src/l4/verifier/playwright.py:47-50`). A
follow-up unit (`<parent>-followup-N`) is verified with its family's criteria: its own delta and its merged parent's
archived delta (`FamilyProvider.criteria` and `merged_parent_criteria`, `src/l4/verifier/fixloop.py:175-205`; L4-FBK-010). The
carry of L4-VER-086 (`ui_step.carried_from_base`, `src/l4/verifier/ui_step.py:228-263`) already turns most of those holds
into notes: the scenario is the base's word for word (C1), every tracing test is a passing `pass_to_pass` test (C2), each
resolves to one file the unit did not change (C3), nobody rejected it (C4).

Re-running that rule (`carry_file` and `carried_from_base` of this branch, 4c8f127d) on the stored evidence of three
follow-up units of one TypeScript web consumer: they raised 40 UI holds on 0.4.59 (7, 10 and 23); the 0.4.60 rule carries
34 of them, leaving 6 (1, 3 and 2). [V: the scripts and data are `analyze.py` and `verify_carry.py` in the analysis folder
of the session that wrote this change; the 40 and the 34 are read from the rounds' `verdict.json` and from the rule's output.]
The 6 that remain are:

- 2 are criteria that the follow-ups' own feedback wrote (a new scenario in the follow-up's delta, traced by new red tests).
  They are real gaps and stay.
- 2 are R1, a stale parent text. The family takes the parent's ARCHIVED delta text, while the pass-to-pass baseline
  (`spec_baseline`, `src/l4/verifier/ladder.py:861-862`) is the CURRENT capability spec at the merge base
  (`criteria.base_criteria_at`, `src/l4/specs/criteria.py:311-329`). When a later change reworded a parent scenario, C1
  fails (`unchanged_ids`, `:344-350`, compares the normalised text under the same id), the old tests get no `pass_to_pass`
  proof, the criterion becomes `uncovered`, and a UI hold and a criterion verdict question follow. Two real cases: a parent
  delta saying `/flows` where the base spec says `/no-such-page-deep-link, a path no feature owns`; a parent delta saying
  "the plan's eight" where the base spec says "the nine calls ... the frozen `calls.test.ts`".
- 2 are R2, a file-level C3. Appending one test to an existing test file lists that file among the unit's changed files
  (`unit_changed_files`, `src/l4/verifier/playwright.py:36-39`, names only) and `carried_from_base` drops every criterion
  that file traces (`ui_step.py:260`). A unit that added one new test (the brief says 11 lines, +11/-0 [U]) to an existing
  file blocked two criteria that way, though the file's old tests, the ones that trace them, were the base's: the file's
  trace holds 15 old tests with the proof `pass_to_pass` and the one new test with a red proof [V]. Their evidence was
  `pass_to_pass` at the head, so C3 was the only condition that failed. In both rounds of that unit step 1's
  `verify.base_tests` event listed the file in `reverted` with empty `failing` and `not_run` [V, the unit's ledger].
  Not read: the added lines themselves. The rule of D2 is stricter than "the added lines lie outside the traced test" (it
  wants whole new tests and nothing else outside the tests), so it refuses the case if those 11 lines include an import or a
  hook; that is the price of D2's argument, and the one thing a reviewer of this change should check against the real diff.

With both fixed the 6 should fall to the 2 real gaps. That is inferred, not simulated: step 4's trace is recomputed after R1
(the stored `uncovered` state is the effect of the stale text), and the consumer's repository was not at hand for R2.

## What Changes

- R1 (L4-VER-096). For an OpenSpec follow-up the family's parent criteria take the base capability spec's text when the base
  holds exactly one criterion with the same id whose text differs; the follow-up's own delta still wins, and the parent's text
  stays when the base has no such criterion, two, no readable base, or for Kiro. The matching key is the criterion id, which
  for OpenSpec already is the hash of capability, requirement name and scenario name (design D1). The rewrite sits in
  `merged_parent_criteria`, so the verifier's steps, the judge, the writers and the red step read one text.
- R2 (L4-VER-097, L4-VER-098). C3 of L4-VER-086 also accepts a changed test file of JavaScript, TypeScript or Python when the
  unit only added whole new tests to it: no deleted or changed line; the base's file ran on the unit's code at step 1 and the
  traced tests passed there; every old test's block is the base's text, the traced ones included, and nothing outside the tests
  changed except the new test blocks (design D2). A block that cannot be found once at each side fails closed. Other
  languages keep the file-level rule.
- The row of the carried criterion names the appended files, and `verify.generated{status: carried}` carries an optional
  `appended` list (design D2).

Non-goals:

- Turning a generator `not_testable` verdict into a note. It would remove no hold once R1 and R2 are in, `not_testable` is the
  writer model's own claim, and the per-criterion hold id and binding of L4-VER-067 stay.
- Proving an implementer-written end-to-end test by running it at the base and at the head: a larger change.
- Fuzzy matching of a reworded scenario (L4-VER-086 says "not done" and stays so): R1 matches by id, which is by name.
- A carry for test files of other languages (Go, Java, C#, ...): the block rule is defined for JavaScript, TypeScript and
  Python only.
- Changing C1, C2 or C4, the writer, the judge, the hold's id or its binding.

R1 and R2 need nothing of each other and can be left out one without the other.

## Capabilities

### New Capabilities

- `ui-carry-followup`: L4-VER-096 (a follow-up reads its merged parent's criteria at the base's wording), L4-VER-097 (a test
  file the unit only added tests to does not keep a UI criterion a gap: JavaScript and TypeScript), L4-VER-098 (the same
  rule for Python).

### Modified Capabilities

Amended in place in `docs/SPEC.md` (a task of this change), each with a pointer to the new requirements:

- L4-VER-086: condition 3 ("not among the files the unit changed") and the "Residual risk" and "scenario restated" sentences.
- L4-FBK-010: the family's parent criteria are read at the base's wording for an OpenSpec follow-up.
- The step 5 row of the verification ladder and change-table row 141 (`ui-carry-unchanged`); the `verify.generated` entry of
  12.1 (the optional `appended` key).
- `docs/runbook.md`: the paragraph that starts `From 0.4.60 a UI criterion that the unit did not change`; `CHANGELOG.md`.

## Impact

- `src/l4/specs/criteria.py` (a pure `read_at_base` over parent and base criteria beside `unchanged_ids`),
  `src/l4/verifier/fixloop.py` (`FamilyProvider.merged_parent_criteria`, `family_of`), `src/l4/implementer/discrimination.py`
  (`unit_base`, shared), `src/l4/verifier/ui_step.py` (`carried_from_base`), a new `src/l4/verifier/carry_appended.py` (the rule
  of D2 for both languages), `src/l4/implementer/test_locate.py` and `src/l4/implementer/tdd.py` (`_test_names_of` moved so
  both read it), `src/l4/verifier/ladder.py` (`_generate_step`, `_carry_files`, the `appended` key), `src/l4/verifier/report.py`
  (`_generated_rows`).
- `docs/SPEC.md`, `docs/runbook.md`, `CHANGELOG.md`. No change to the configuration, the skill or `src/l4/s1/`.
- Ledger and files: one optional key `appended` on `verify.generated`; an older reader ignores it.
- Behaviour: a follow-up of an OpenSpec unit whose parent scenario a later change reworded no longer asks about it as a UI hold
  and a verdict question when its tests pass; a unit that only appended tests to a changed test file no longer asks about the
  criteria that file traces. A person's accept bound to the old text of a rewritten criterion is void once. Nothing changes for
  a Kiro follow-up, a changed or new scenario, or a file the rule cannot read.
