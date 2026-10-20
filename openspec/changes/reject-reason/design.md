## Context

`proposal.md` describes the report. This change makes a person's reject, not the judge's suggestion, decide what a fix
task is checked against, keeps every reject a task consumes in its text, and makes the verdict questions say how a
person sets that check. It is built for 0.4.21 on top of the released 0.4.20 (da3e7c28).

Labels: [V] verified in the code, the tests or a reproduction at da3e7c28 (file:line); [I] inferred; [U] unknown, not
checked here. The reproduction called `plan_fix_unit` with the consumer's finding (spec gap, criterion `Req 6.10`, the
judge's suggestion "… THEN the command exits 2 …") and rendered the Kiro `bugfix.md` (`_FixItems`) and the OpenSpec
delta (`_requirement`) for five answers; it is not in the repository.

How a person's reject reaches a fix task today [V]:
- `consume_verdicts` records `human.verdict{question, target, decision, by: "human", reason}` (`verdicts.py:353-383`;
  the reason is cut at 1000 characters, `:379`). `effective_verdicts` keeps the latest per target until a fix unit
  consumes it (`:386-432`).
- A rejected judge-only finding becomes the human's: `source: "human"`, its detail ends ` [rejected by human
  (<reason>)]` (`apply_finding_verdicts`, `:477-490`; `rejection_note`, `:493-496`). A rejected criterion becomes a
  `fail` outcome `rejected by <by>: <reason>` (`aggregate.py:61-64`). Either makes the round FAIL (`aggregate.py:105-109`).
- `plan_fix_unit` (`fixunit.py:286-353`) groups the FAIL's human and deterministic blockers per criterion
  (`_candidates`, `:137-220`). Per finding: `verdict = rejects.get(f.id) or rejects.get(criterion)` (`:176`);
  `scenario = when_then(verdict.reason)` (`:177`); **when that is None and the finding is a spec gap, `scenario =
  when_then(f.suggested_fix)` (`:178-179`)**. The decision `Q-NNN: <reason>` comes from that one `verdict` (`:207-211`);
  both the finding's and the criterion's questions are consumed (`:217-219`).
- The task's text is `Decided by <by> in <decisions>. <the judge's detail>` (`_fit_detail`, `:101-110`), written first
  into the OpenSpec `proposal.md` (`openspec.py:458-462`) and the Kiro `bugfix.md` `1.n` and `design.md`
  (`kiro.py:639-647`, `_fix_design`). A scenario becomes an ADDED requirement `<requirement> — regression <n>`
  (`_requirement_for`, `:258-276`); on Kiro it is one more `2.n` of "Expected Behavior (Correct)" next to the restated
  criterion, and the task's `_Requirements:_` cites both (`_FixItems`, `kiro.py:577-620`).
- The implementer's red prompt lists the criteria the task links (Kiro) or all of the family's (OpenSpec) and requires a
  new test for each (`prompt.py:185-206`, `red.md:5-10`). The `single` and `single_tests` prompts say that a decision
  `Decided by … in Q-…` is binding (`single.md:6`, `single_tests.md:9`); the red and green prompts do not.
- The judge's spec-gap `suggested_fix` is "exactly one sentence of the form WHEN … THEN <the behaviour the committed
  code shows for it> … it must describe what the code does now" (`judge.py:182-185`).

The reproduction [V]:
- A: the finding rejected with the person's `WHEN … THEN … exits 1` (the consumer's real answer): the scenario is the
  person's; correct.
- B: the same reason cut before `WHEN`: the delta pins `THEN the command exits 2 …`; Kiro `bugfix.md` has `2.1` "… exits
  1 … (parent Req 6.10, C-…)" and `2.2` "… exits 2 …", the task cites `2.1, 2.2`.
- C: the finding rejected without a scenario (Q-013) and the criterion rejected with one (Q-011): consumed `[Q-013,
  Q-011]`, the decisions name Q-013 only, the scenario is the judge's "exits 2"; Q-011's text is in no file.
- D: a bare `reject`: as B, with `Decided by human in Q-013: rejected, no reason given.`
- E: only the criterion rejected, no scenario: a synthetic task on the criterion, no delta; correct.

## Goals / Non-goals

Goals: a fix task built from a person's reject is checked against what the person said (their `WHEN … THEN …`, else the
cited criterion as written), never against the judge's description of the current code; every consumed reject is in the
task's text; a verdict question tells the person how to set that check.

Non-goals:
- A model, S1 call or text match that decides whether a reason agrees with the judge's suggestion (D1).
- Changing the judge prompt. Its spec-gap suggestion describes the code as it is, which is the right scenario for a gap
  that nobody disputes (D1).
- A MODIFIED delta of the parent's criterion when a person's scenario contradicts it: fix units never modify the
  parent's requirements (L4-OSP-006); unchanged.
- The red and green prompt templates (open question 3).
- The hold questions and the judge findings a hold quotes (`_quote`, `verdicts.py:167-169`): the quote is labelled "The
  judge's finding on the same subject …", comes after the decision, and its task is a chore whose prompt makes the
  decision binding. Unchanged.

## D1. The scenario of a rejected finding comes only from a person (L4-VER-059)

Decision:
- The verdicts of a finding are, in order, the reject of the finding (`rejects[f.id]`) and the reject of its cited
  criterion (`rejects[criterion]`), each when present.
- Its scenarios are the `when_then(reason)` of each verdict that has one, the finding's first; a text the task already
  pins is not added again (as today, `fixunit.py:215`). Every scenario stays attached to the finding (`(f.id, f.title,
  text)`), so `_requirement_for` and the scenario names are unchanged.
- `when_then(f.suggested_fix)` is used only when the finding has no verdict at all and is a spec gap: the minor on a
  PASS with `verifier.fix_minor_findings` (`:158-164`), the one path where the judge's suggestion is the source today and
  no person spoke. Then nothing changes, including `test_fixunit.py:90-162` and `test_ladder_fix.py:265`.
- A finding with a verdict and no scenario: the task cites its criterion and pins nothing for it. On OpenSpec the fix
  unit has no delta from it (`skip_specs: true` when no other task adds one, `openspec.py:316-318`); on Kiro `bugfix.md`
  restates only the criterion as `2.n` (`kiro.py:594-596`). The red step then tests the criterion's own scenario.
- Without a criterion (the judge named a criterion the unit does not have, so `judge_findings` dropped it,
  `aggregate.py:89-102`): the existing rule for a human finding with no criterion and no scenario applies
  (`fixunit.py:180-189`): listed `rejected with no criterion and no WHEN ... THEN ...: answer again with a scenario`, not
  consumed. Today such a spec gap became a task from the judge's suggestion.

Why drop the suggestion and not keep it as labelled context:
- By `judge.py:182-185` a spec-gap suggestion is the code as it is now. A reject says the code is wrong, so after a
  reject the suggestion is the behaviour in dispute, never a valid check. Where it happens to agree (a person who wants
  the gap pinned as it is), copying the sentence into the reason pins it, and the question says so (D3).
- A concrete `WHEN … THEN …` in a red step's context is what a model writes its test from; `red.md:10` even names "a
  regression scenario that pins what the code does now" as the already-satisfied case. A label does not stop that.
- The judge's reasoning is not lost: the finding's own `detail` stays in the task after the decision (`_fit_detail`).
  The consumer's finding shows why that is enough: its detail said "requires exit 1 … the code exits 2", which agrees
  with the person, while its suggestion pinned exit 2.

Alternatives rejected:
- Keep the suggestion as a labelled line (`The judge suggested, not adopted: …`). Rejected for the second reason above.
- Drop it only when it contradicts the person (compare the THEN clauses, or ask S1). No deterministic test tells
  agreement from contradiction in free text, and the verifier's rule is that no model decides what a person's answer
  settles (L4-VER-013, "One question per subject"). A model call in the pure planner would add cost and a failure mode.
- Keep it for a bare `reject` (no reason), reading the bare reject as "fix it as suggested". The consumer's finding is
  the counterexample: its title claims a defect ("exits 2, not 1") and its suggestion pins it (exit 2); a bare reject
  there would pin the defect. The question now says how to pin the suggestion.
- Refuse a reject of a spec gap without a scenario as an invalid answer. A reason alone is a sound answer when the
  criterion already states the expected behaviour (the consumer's criterion said exit 1), and a refusal costs a person a
  round trip.

## D2. Every reject a task consumes is in its text (L4-VER-059)

Decision:
- The decisions of a task are `<question>: <reason or 'rejected, no reason given'>` for every verdict of every finding
  of the task (D1 order), each once, in the order found. `_fit_detail` keeps its form `Decided by <by> in <d1>; <d2>.`
  and its budget (each decision at least 100 characters, together `MAX_DECISION_CHARS`, `fixunit.py:101-110`), so
  `decision_calling_code_wrong` (`tdd.py:1968-1987`, which reads `Decided by \w+ in Q-NNN: …`) and the Kiro `_defect`
  (`kiro.py:558`, `_DECIDED`) read it as before. Two questions with the same reason are two decisions (the consumer's
  Q-011 and Q-013): the text is short, and merging them into `Q-013, Q-011: …` would break the `Q-\d+:` match of
  `tdd.py:1968`.
- `decided_by` stays the `by` of the last decision added, as today (`:211`).
- The note `apply_finding_verdicts` appended is stripped with the finding's own verdict (`rejects[f.id]`), as today
  (`:197`); a criterion's verdict appended no note to the finding.
- What is consumed does not change (`:217-219`): the finding's and the criterion's questions.
- [V] A throwaway prototype of D1 and D2 (reverted, not committed) gave the intended plans for the five answers of the
  reproduction (B and D: no delta, Kiro `2.1` only; C: both decisions, Q-011's scenario) and passed the 178 tests of
  `test_fixunit.py`, `test_ladder_fix.py`, `test_legacy_round.py`, `test_hold_verdicts.py`, `test_verdicts.py`,
  `tests/unit/specs/test_kiro_fix_unit.py`, `test_fix_unit.py`, `test_fix_unit_test_only.py` and
  `tests/unit/implementer/test_decided_tests_chore.py` unchanged.

Why: a reject that is consumed is answered for good (`effective_verdicts` drops it, `verdicts.py:425-428`). One that is
consumed but quoted nowhere is a person's decision the implementer never sees.

## D3. The verdict questions say how to set the check (L4-VER-060)

Decision (texts in Contracts, word for word):
- `_finding_question` (`verdicts.py:543-561`): the answer line also says that the reason comes first in the fix unit;
  a second line says how to set the check, by whether the finding cites a criterion; for a spec gap with a suggested
  fix, a third line says that the suggestion describes the code as it is now and that a reject does not use it. The
  options become `accept` and `reject: <reason>, then WHEN ... THEN ... to set the check`.
- `_criterion_question` (`:507-540`): the line "If the code is right and the scenarios are incomplete, `reject` with a
  scenario: WHEN ... THEN ..." is replaced by the line that says how to set the check against "the scenario above"; the
  options as for a finding.
- `_hold_question` is unchanged, its options included (`("accept", "reject: <reason>")`, `:617`): a scope or coverage
  hold's reject is a chore whose reason is a decision, not a scenario; an other hold already asks for the sentence
  (`:593-598`); a judge-view hold must never get one, and `test_hold_verdicts.py:505` asserts that its question holds no
  `WHEN` [V: a prototype that changed the hold's options too failed exactly those three cases].
- The header comment of `questions.md` (`l4:questions v1`) is unchanged [I: it is the file's format marker, rewritten
  by the questions writer].
- No test pins today's texts [V: `grep` of `tests/` for "to waive the finding", "scenarios are incomplete" and "for a
  spec gap" finds none; a throwaway prototype of D3 passed `test_verdicts.py`, `test_hold_verdicts.py`,
  `test_supersede_verdicts.py` and `test_verdict_reentry.py`, 100 tests]. The recorded `docs/live/**/questions.md` files
  are evidence of past runs and stay.

Why the words matter: the person decides between three outcomes (their scenario, the criterion as written, nothing
convertible) and today's text names none of them; and the consumer's person added their own `WHEN … THEN …` on their own,
which the next person may not.

## D4. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`: L4-VER-059 at the end of §10.7's L4-VER-006 text (before L4-VER-007); L4-VER-060 at the end of
  L4-VER-013's text (before L4-VER-014); the L4-VER-006 sentence "A finding with `spec_gap: true` produces … an
  **ADDED** regression requirement with a scenario" says "when L4-VER-059 gives it one"; the Given of SCN-VER-18 names
  the two sources; SCN-VER-205 to SCN-VER-214 after SCN-VER-157 (the end of §23.9); one change-table row. This branch
  already holds that SPEC text.
- `docs/runbook.md`, "For verdict questions": the `WHEN … THEN …` bullet says what a reject without one does, that the
  suggested fix is not used, and that both answers of a criterion and its finding reach the fix unit.
- Skill `plugins/l4/skills/l4/references/operate.md`, "Verdict questions": the same in two sentences.
- `CHANGELOG.md`: `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)` with `### Changed` and `### Fixed` (the lines
  are in `tasks.md`). Other 0.4.21 changes add the same heading; whoever merges second keeps one heading and merges the
  lists under the same subheadings.

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.verifier.fixunit`: `plan_fix_unit`, `when_then`, `FixPlan` and `_fit_detail` keep their signatures. New private
  helper `_verdicts_of(f, criterion, rejects) -> list[HumanVerdict]` (D1 order, no duplicate question).
- Not-converted text for a rejected finding with no criterion and no scenario: unchanged, `rejected with no criterion
  and no WHEN ... THEN ...: answer again with a scenario` (`fixunit.py:184`).
- `l4.verifier.verdicts` texts (module constants, so tests import them):
  - `REJECT_OPTION = "reject: <reason>, then WHEN ... THEN ... to set the check"`; both question kinds use `("accept",
    REJECT_OPTION)`.
  - Finding question, the answer line: ``Answer `accept` to waive the finding, or `reject` and say why: a rejected
    finding is fixed by a fix unit, and your reason comes first in it.``
  - `CHECK_WITH_CRITERION = "To set the check the fix must pass, end the reason with one sentence WHEN <the situation>
    THEN <the behaviour you expect>, with WHEN and THEN in capitals: it becomes a scenario of the fix unit. Without one,
    the fix is checked against {target} as it is written."`; `{target}` is `criterion <C-id>` for a finding and `the
    scenario above` for a criterion question.
  - `CHECK_WITHOUT_CRITERION = "This finding cites no criterion: end the reason with one sentence WHEN <the situation>
    THEN <the behaviour you expect>, with WHEN and THEN in capitals, or no fix can be made from the reject."`
  - `SUGGESTION_IS_THE_CODE = "The suggested fix describes what the code does now, and a reject does not use it: to pin
    that behaviour, end the reason with it."` (a spec gap with a non-empty `suggested_fix` only).
  - The criterion question keeps "Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why."
    and follows it with `CHECK_WITH_CRITERION` for `the scenario above`, in place of the "If the code is right …" line.
- No ledger event, configuration key, fix-unit file format or prompt template changes.

## Collisions

- Other drafts of 0.4.21 run in parallel with other id ranges (this one: L4-VER-059, L4-VER-060, SCN-VER-205 to
  SCN-VER-214). They may insert SPEC text at the same places (the end of §10.7, the end of §23.9) and add a change-table
  row with the same next number (`59` here); whoever merges second renumbers the row and keeps both texts. The docs test
  of this change checks the row by its name, not its number.
- `CHANGELOG.md` `## 0.4.21 (unreleased)`: merged as in D4.
- A delegate that answers verdict questions (another branch) records `human.verdict` with another `by`; D2 keeps `by`
  as it is, so `Decided by <by>` shows it.

## Risks

- A rejected spec gap whose criterion the unit does not have, answered without a scenario, no longer converts; when it
  is the round's only finding, the unit escalates with `no_convertible_finding` where today it got a fix unit (with the
  judge's suggestion, which is right only when the person agreed with it). The question now says the scenario is needed,
  and the runbook's way out (`--replace` with a scenario, or a behaviour feedback item) applies. CHANGELOG says so under
  Changed.
- A rejected spec gap with a criterion that already passes and no person's scenario gives a task the red step may find
  already satisfied; the gap is then not pinned, and the next round's judge may raise it again as a new question [I].
  That costs a round; pinning the wrong behaviour costs a contradictory or wrong fix. The question tells the person to
  give the scenario.
- A task whose finding is about tests, on a criterion the round found satisfied, with no scenario, is a test chore
  (`_about_satisfied_tests`, `fixunit.py:89-98`). With the judge's suggestion gone, a rejected spec gap of that kind is
  now such a chore; its prompt makes the decision binding (`single_tests.md:9`) [V: the rule, I: how often].

## Out of scope / follow-ups

- The red and green prompts could carry the decision rule that `single.md:6` has (open question 3).
- A person's scenario that contradicts the parent's criterion still leaves the fix unit with both (no MODIFIED deltas,
  L4-OSP-006); a person changes the parent's spec on the unit branch for that.
- `verification.md` could list "suggested fix not used: rejected by Q-NNN" per finding.

## Open questions (each with the recommended answer)

Every recommended answer below is taken in this draft (the owner's rule: the decision is in this design, the
requirement and a scenario).

1. Drop the judge's suggestion, or keep it as labelled context? Taken: drop it from every task with a person's reject
   (D1, L4-VER-059, SCN-VER-205, SCN-VER-207).
2. Does a bare `reject` (no reason) still pin the suggestion? Taken: no, the same as a reason without a scenario (D1,
   SCN-VER-206).
3. Add the decision rule of `single.md:6` to `red.md` and `green.md` ("a task whose text starts with a decision by a
   person: your tests and change MUST do what it describes")? Recommended: not in this change. With D1 the check no
   longer contradicts the person, the decision already opens the unit's context, and a template change bumps the
   prompt versions that four test files pin (`tests/unit/implementer/test_prompt*.py`, `test_suggested_edit.py`). Take it as its own change if a fix unit is seen to follow the judge's
   detail over the decision.
4. Is a rejected spec gap with no criterion and no scenario converted from the suggestion as before? Taken: no, it is
   not converted (D1, SCN-VER-209), as every other rejected finding without a criterion and a scenario.
5. Merge two decisions with the same reason? Taken: no (D2).
