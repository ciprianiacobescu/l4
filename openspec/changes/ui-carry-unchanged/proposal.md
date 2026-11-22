## Why

Every criterion of a unit that changed a UI path is UI-facing (L4-VER-014), and a UI criterion that no proved
end-to-end test traces is a step-5 gap: the writer is asked for a browser test that fails at the merge base and passes
at the head. For a criterion the unit did not change, whose behaviour is already in the base, no such test can exist: a
faithful test passes at the merge base and step 5 calls it `non_discriminating` before it runs the head. The gap then
ends as a hold in every case, and L4-VER-067 keeps that hold on purpose when only `pass_to_pass` tests trace the
criterion. The hold asks a person to accept on evidence (the writer's run at the merge base) that says nothing about the
head.

Evidence from a TypeScript web consumer:

- A feedback follow-up of a merged unit changed one web file. Every criterion of its family became UI-facing. Three of
  its parent's criteria, word for word as the archived specs hold them and traced by the parent's passing unit tests
  with the proof `pass_to_pass`, had no end-to-end test. The writer answered `not_testable` twice and wrote one test
  that failed at the merge base and at the head; each became a UI hold, and only the owner could answer them, because
  the follow-up ran outside a plan.
- In another unit a scenario restated word for word under a `MODIFIED` requirement was `pass_to_pass` and covered, and
  still raised a UI hold; the delegate accepted it because the unit had kept the scenario unchanged.

The backlog note said that scenarios restated under `## MODIFIED Requirements` become new criteria whose tests have no
red record. Read in the code, that is wrong for a scenario restated word for word: L4-VER-009 gives its tracing tests
the proof `pass_to_pass` (`verifier/traceability.py:218,232`, `specs/criteria.py:332-349`), by its id (capability,
requirement name, scenario name) and its text after `normalise`. The case of four questions in one unit was another
one: each of the four restated scenarios had gained the same two words (once or twice) that point its harness at the
base's test plan, so their criteria were rightly new (`no proof that it discriminates`), and the one scenario restated
word for word was `pass_to_pass`. They were criterion questions, not UI holds. This change keeps exact identity and
adds no fuzzy matching, so that case stays as it is: two words can change what a scenario means, and a test that is the
base's cannot prove the new words.

## What Changes

- Before step 5 asks the writer about a UI criterion with a gap (after the waiver of L4-VER-067), the criterion is
  *carried from the base* when it is unchanged on the base (L4-VER-009's rule), every test that traces it is a passing
  `pass_to_pass` test in a file the unit did not change, and no reviewer ever rejected it or one of its UI holds. A
  carried criterion gets no writer call and no hold. It is listed: `verify.generated{status: carried, covered_by}`, its
  row in the generated UI tests table, step 5's note, and its minor gap finding, which says so.
- A carry passes nothing: the criterion still needs an adequate passing tracing test and the judge's pass
  (L4-VER-003).

SLIPPABLE: this loosens the gate of L4-VER-067 for one case, and reverses for that case the rule 0.4.56 chose on
purpose (the hold stays when only `pass_to_pass` tests trace a criterion). It is its own change and its own requirement
so that it can be cut at integration without touching `ui-hold-evidence`. Recommended: ship it. Replayed on the
evidence, all its conditions hold for the follow-up's three held criteria and for the restated scenario; design.md D4
says why it is safe and what risk is left.

Non-goals: which criteria are UI-facing; fuzzy matching of scenario text; the waiver; a criterion with any proof but
`pass_to_pass`; a browser check of a carried criterion (D7).

## Capabilities

### New Capabilities

- `ui-carry-unchanged`: L4-VER-086 (a UI criterion that the unit did not change is carried from the base, not held).

### Modified Capabilities

- L4-VER-067: the hold stays when only `pass_to_pass` tests trace a criterion, except for a criterion carried from the
  base.

## Impact

- `src/l4/verifier/ui_step.py` (`carried_from_base`, `carry_file`, `rejected_ui_criteria(events, criteria)`,
  `unclosed_holds`, `gap_findings`; `lost_notes` stays as it is), `src/l4/verifier/generate.py` (`ui_gap_finding`), `src/l4/verifier/ladder.py`
  (`_Run.unchanged`, `traceability`, `_generate_step`), `src/l4/verifier/types.py` (`GenStatus`),
  `src/l4/verifier/report.py` (`_generated_rows`), `src/l4/verifier/fixunit.py` (the closed gaps).
- `docs/SPEC.md` (L4-VER-086, SCN-VER-343..349 and SCN-VER-351, change-table row 141, the amendment to L4-VER-067, the
  step-5 row of 10.2, `verify.generated` in 12.1), `CHANGELOG.md`, `docs/runbook.md`.
- No new event, no configuration key, no template change; a new value of `verify.generated.status`.
