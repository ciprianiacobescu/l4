# An accepted UI criterion is not held again in every later round

## Why

A consumer's unit had a UI criterion served by a unit-level e2e helper [V, 2026-10-29]: round 1 raised the UI hold
H-addeb9d5 (`fails_at_head`), a person accepted it together with a verdict question on the criterion (accept); round 3
raised a new hold H-8f5a5712 (`not_testable`) for the same criterion, and round 5 H-1208e5d8 (`uncollectable`). Each
new hold was a new question for a person and cost a run.

Two causes (verified):
- the hold's id is `H-` + 8 hex of sha256 of its text, and the text names the generator's status
  (`ui_step.unclosed_holds`), so every new status is a new hold, although its docstring says the text is stable;
- step 5 (UI test generation) never reads the verdicts: answers are applied in `_finalize`, after the writer was called.

## What changes

- The UI hold's text no longer names the status (`UI criterion C-… has no end-to-end test; see the generated UI tests
  table`); the status stays in the table and in `verify.generated`.
- A UI hold's accept is bound to the hold, the criterion's text and the criterion's tracing-test files (the evidence the
  person accepted), like a `judge view:` hold's. An accept of the criterion itself stays bound to its text only
  (L4-VER-013). The status and the writer's reason, which the hold no longer names, are in the hold's question (not
  hashed) and in the delegate's material, with how long an accept lasts.
- Before step 5 calls the writer, a criterion is *waived* when an accept on the criterion is in force, or the latest
  accept of any UI hold of the criterion is in force (found by a new `question.raised{criterion}` field, or, for a
  ledger written before this change, by the hold's title). A waived criterion records
  `verify.generated{criterion, status: "waived", by}` with no writer call and no hold; the minor gap finding stays,
  with "waived by …".
- A waiver ends when the criterion's text or its tracing-test files change (a criterion verdict's accept: its text
  only), on a `human.void`, or a later reject, also one a fix unit consumed. A failing tracing test suspends it for that
  round: it waives again once the test passes. A criterion whose own verdict in force is a reject is never waived.

## Impact

- Code: `l4.verifier.ui_step`, `l4.verifier.ladder` (`_generate_step`, `_finalize`), `l4.verifier.verdicts`,
  `l4.verifier.types` (`GenStatus`).
- Spec: L4-VER-067 added; L4-VER-013 (holds paragraph), L4-VER-014, the step 5 row and the `verify.generated` note
  amended; SCN-VER-247 to SCN-VER-252; change-table row 94.
- Risk: an accept given on `fails_at_head` survives later UI rework that does not touch the tracing tests.
