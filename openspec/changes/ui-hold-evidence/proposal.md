## Why

A UI criterion that step 5 cannot close is a hold (L4-VER-067), and its verdict question decides whether the unit goes
on. When the test the verifier wrote fails at the head, the person or the delegate who answers must tell whether the
test or the product is wrong. The question does not let them.

Evidence from a TypeScript web consumer, four units: the delegate and a person could not tell, round after round,
whether the generated browser test or the product was wrong ("I cannot tell why the verifier's generated test fails at
the head, since its file is not in the tree"). In at least four cases in three units the generated test failed on its
own wrong premise: it put a session into the browser's storage while the app reads the session from an API call; it
opened a route without the prefix the app uses; its mock of the session call had no user and no CSRF token. Each case
cost a person or a delegate round. In two units a reviewer rejected a criterion and its UI hold in the same round with
near-identical reasons; each time the fix unit got two tasks for one behaviour (the second one "already satisfied") and
two new criteria with the same scenario text, and the next round asked about both again.

What exists at 0.4.59 (read in the code):

- `verifier/generate.py:218-221`: a test that fails at the head ends `fails_at_head` with the reason `the test fails at
  the head: <ids>` and the paths of its traces and screenshots. The head run's report, which holds the failure text, is
  not kept. `generate.py:285-288` removes every generated file that was not accepted, from both trees.
- `GeneratedOutcome.code` keeps the last test written (`verifier/types.py:206`). `verdict.json` stores it cut at 4,000
  characters (`verifier/report.py:357`), and `write_round_evidence` redacts the whole object after that cut
  (`report.py:427`): cut, then redact. `verification.md` shows the path and the artefact paths only.
- The hold's question (`verifier/verdicts.py:672-686`, `_ui_hold_lines`) says `Step 5 for C-…: <status> after <n>
  attempt(s); <reason>`, the reason cut at 300 characters: test ids, never the failure or the code. The delegate's
  material (`delegate/prompt.py:482-491`, `_generated_row`) gives the same line.
- The writer's retry after `fails_at_head` (`generate.py:296`) gets `last.reason` as its retry reason: the ids only, so
  the second attempt is written blind.
- A rejected UI hold becomes a finding with no criterion (`verdicts.py:225-265`, `_hold_finding`; title `Rejected
  hold: UI criterion C-… has no end-to-end test; see the generated UI tests table`, `verdicts.py:261`). The fix planner
  keys it by the hold's id (`verifier/fixunit.py:289`), so it is a task of its own, and a rejected criterion of the same
  round gets the synthetic `Criterion … fails` task of its own (`fixunit.py:232-238`). Each task pins its own copy of
  the scenario (`fixunit.py:315-317` deduplicates within a task only). With several requirements in the parent, the
  hold's scenario goes under `Rejected hold: UI criterion … — finding H-…` (`fixunit.py:375`), named after the hold's
  text (`fixunit.py:425`).

## What Changes

- Step 5 keeps, for a test that fails at the head, a bounded excerpt of the failure of the head run (the retry
  prompt's excerpt, L4-IMP-064: `E` lines and the deepest repository frame per test, at most 40 lines and 3,000
  characters, redacted), and keeps the last test written as a bounded copy that is redacted whole before it is cut
  (4,000 characters, cut at a line end, redacted again). `verdict.json` stores both (`generated[].excerpt` is new,
  `generated[].code` is now redacted before its cut).
- The hold's question carries the excerpt and the code, with the test's path, in its `### Harness notes` subsection
  (L4-IMP-102), never in the hold's text, title or Context. `verification.md` gets a section that shows them for each
  generated test that was not accepted.
- The writer's retry after `fails_at_head` gets the excerpt with the reason.
- A rejected UI hold cites its criterion. When the criterion's own reject is in force in the same round, the hold's
  finding joins the criterion's task: one task, both decisions, both questions consumed, one scenario when the two
  scenarios are the same text. A rejected UI hold alone with a `WHEN … THEN …` gets its scenario under the criterion's
  requirement (`<requirement> — regression <n>`), named after the criterion's scenario.

Decided against, with reasons in design.md: marking a generated test that fails at the head only by a wait timeout as
a writer failure (D6), and showing the writer an existing passing e2e test of the same page (D7, a follow-up).

Non-goals: the hold's text and id, the accept binding of L4-VER-067, what a `reject` or an `accept` settles, the
ledger's `verify.generated` event, the writer's template, the traces and screenshots (they stay on the runner).

## Capabilities

### New Capabilities

- `ui-hold-evidence`: L4-VER-083 (a UI hold shows the generated test and its failure at the head), L4-VER-084 (the
  writer's retry carries the failure), L4-VER-085 (a rejected UI hold is fixed under its criterion).

### Modified Capabilities

- L4-VER-067: the hold's question also holds the harness notes of L4-VER-083; the hold's text, id and binding are
  unchanged.
- L4-VER-006: the parent requirement of a rejected UI hold's scenario is its criterion's.

## Impact

- `src/l4/verifier/generate.py` (`_Verdict.excerpt`, `_discriminates`, `generate_ui_test`, a bounded code copy),
  `src/l4/verifier/types.py` (`GeneratedOutcome.excerpt`), `src/l4/verifier/report.py` (`_generated_json`, a new
  section in `render_verification_md`), `src/l4/verifier/verdicts.py` (`_ui_hold_notes`, `_hold_question`,
  `_hold_finding`, `is_ui_hold_finding`), `src/l4/verifier/fixunit.py` (`_candidates`), `src/l4/implementer/excerpt.py`
  (a public name for the redact-then-cut helper, if the implementer adds one).
- `docs/SPEC.md` (L4-VER-083..085, SCN-VER-331..342 and 350, change-table row 137, amendments to L4-VER-006, L4-VER-067 and the
  step-5 row of 10.2), `CHANGELOG.md`, `docs/runbook.md`, `plugins/l4/skills/l4/references/operate.md`.
- Sizes: a hold's question grows by at most about 7,800 characters (3,000 of excerpt, 4,000 of code, line numbers); a
  `verdict.json` by at most 3,000 characters per generated test that fails at the head. No new ledger event, no
  configuration key, no template change.
