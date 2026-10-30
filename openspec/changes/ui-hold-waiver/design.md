# Design: ui-hold-waiver

## Context (verified on amaster e66cde82, read-only analysis of 2026-10-30)

- `_generate_step` (verifier/ladder.py) calls `unclosed_holds` (ui_step.py), whose text is `UI criterion {id} has no
  end-to-end test ({status}); see the generated UI tests table`; `hold_id` = `H-` + sha256(text)[:8] (verdicts.py).
- An accept is `human.verdict{target: H-…, text_sha256: sha256("H-…")}`; `_finalize` builds `current[hold_id(h)]`,
  then `effective_verdicts` and `unresolved_holds`, after step 5 has spent the writer call.
- A criterion verdict accept (`_criterion_question`) records `text_sha256(criterion)` and stays in force until the text
  changes or `human.void`; it is voided by a failing tracing test only in `_finalize`.
- The judge follow-up already skips decided criteria with `effective_verdicts(events, {c.id: text_sha256(c)})`.
- `judge view:` holds bind their accept to `hold_views[hold].sha` (hold text + criterion digest + files digest).

## D1 A stable hold

`unclosed_holds` writes `UI criterion {id} has no end-to-end test; see the generated UI tests table`. The hold's
binding is a `hold_views`-style sha over the hold text, `text_sha256(criterion)` and the head blobs of the criterion's
tracing-test files (step 4's trace); `current` in `_finalize` uses it for UI holds. A test id is mapped to its file by
`file_of_test`, else by `test_locate.file_of_id` over the work tree's files (TypeScript and other ids). The hold's
question (not hashed) gives step 5's status and reason and says an accept lasts until the criterion's text or its
tracing tests change; the delegate's material for the hold carries the criterion's generated-tests row.

## D2 The waiver

`ui_waivers(events, criteria, trace, blob_of) -> dict[criterion_id, str]` (the Q-/H- id that waives) in `ui_step.py`:
- an accept on the criterion (`C-…` target) in force by `effective_verdicts` with the current `text_sha256` (bound to the
  text only, as L4-VER-013 says: it records no tracing-test digest);
- the latest accept of a UI hold of that criterion whose binding equals the current one; the criterion is found by
  `question.raised{criterion, criterion_sha256}` (written from now on) or, for older ledgers, by the title regex
  `^Hold (H-[0-9a-f]{8}): UI criterion (C-[0-9a-f]{8}) has no end-to-end test`.
A hold whose id is not the stable one (an older text, also one raised by this harness for a ledger restored from an
older run) is found the same way and compared with the hash of its id, as its accept was recorded, so it carries no
binding: it survives a change of the criterion's text or tracing files (criterion ids do not hash the text).
Not in force: a later reject over the raw `human.verdict` events of the criterion and its holds (a reject that a fix unit
consumed counts: `effective_verdicts` drops it), a `human.void`, a criterion verdict in force that is a reject, and, for
that round only, a failing tracing test (`trace.state == "fail"`; no `human.void` is written for a hold's accept, and it
waives again when the test passes).

## D3 Where

In `_generate_step`, after `plan_generation` and before `gap_findings`, the writer and both hold branches; `events`
is passed in from `verify_unit`. A waived criterion records `verify.generated{criterion, status: "waived", by,
attempts: 0}` (add `"waived"` to `GenStatus`); `unclosed_holds` treats `waived` as closed; the minor gap finding says
`waived by …`. When every gap is waived, `generate_ui_tests` returns before the base checkout.

## D4 Not changed

Only `accept` waives. A rejected hold keeps `settle_holds`/`_hold_finding`; a rejected or failing criterion is never
waived. A delegate's accept waives as today's accepts do.
