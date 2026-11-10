## Why

In a consumer run, a unit that changed one web file (a file under `verifier.playwright.ui_paths`) had 10 criteria.
Step 5 treats every criterion of such a unit as UI-facing (`playwright.ui_facing_criteria` returns all of them as soon
as one changed file matches), and a UI criterion is a gap until a proved end-to-end test traces it, however many unit
tests do (L4-VER-014). So all 10 were gaps and the UI test writer was asked for each. It returned `not_testable` for 8
of them ("pure functions", "no browser-observable behavior"), and those 8 were the criteria that step 4 had already
covered with discriminating red-then-green tests (step 4's note: 8/10 criteria covered). `ui_step.unclosed_holds`
makes a hold of every gap whose outcome is not `accepted` or `waived`, so the round raised 10 UI holds: 12 verdict
questions in all for the delegate or a person, nearly all of them noise.

The same run showed a second cause of holds. Generated end-to-end tests failed, or the writer declared the criterion not
testable, because the writer did not have the e2e suite's own helpers: a sign-in helper, the test users, an
accessibility assertion ("needs the suite's login() ... helpers"), all defined in the suite's `e2e/conftest.py`. Today
the writer is shown the criterion, the unit's diff of the UI files and the page the head app served, and nothing of the
suite. One generated file was also uncollectable.

## What Changes

- A UI criterion that step 4 covers with a discriminating test, and for which the writer returns `not_testable`, is a
  **note** and not a hold: its row of the generated UI tests table keeps the status `not_testable` and the writer's
  reason and adds `covered by step 4: <tests>; a note, not a hold (L4-VER-067)`; `verify.generated` and the stored
  outcome carry `covered_by` (the covering tests); no hold is raised, no fix unit is made for its gap, and step 5's note
  counts the notes. The minor gap finding stays.
- "Covered with a discriminating test" is read from the round's trace (`VerifyResult.trace`) as it stands when step 5
  starts: state `covered`, no `held` reason, and at least one passing tracing test whose proof a run showed (any proof
  but `pass_to_pass`, and no label of a red record that no run proved). Step 5 already holds that trace; nothing new is
  carried from step 4. A round whose steps are reused keeps the stored outcome and holds and decides nothing again.
- The hold stays when nothing discriminating traces the criterion, for every other outcome of the writer (a writer
  failure, an uncollectable file, a test that fails at head, two non-discriminating attempts, a base that errors or
  cannot be served, a lint failure), and when no writer is configured.
- The UI test writer is shown the e2e suite's support files as they are at the merge base: `e2e/conftest.py` and the
  other `.py` files under `e2e/` that are not test modules, at most 6 files, each cut at 8,000 characters and 20,000
  characters together, the rest named; its e2e rules say to use their fixtures and import their helpers
  (`testwriter@7`). No configuration key is added (L4-VER-077).
- Not changed: which criteria are UI-facing (still every criterion of a unit that changed a UI path); which criteria
  are gaps and so asked of the writer; the waiver of L4-VER-067; the hold's text and binding; the gap finding's text;
  the judge's prompt.

## Impact

- Code: `l4.verifier.ui_step` (`covered_by_step4`, `lost_notes`, `unclosed_holds`), `l4.verifier.types` (`GeneratedOutcome.covered_by`),
  `l4.verifier.generate` (`generate_ui_tests` takes `covered` and reads the support files; `generate_ui_test` takes
  them as blocks), `l4.verifier.ladder` (`_generate_step`), `l4.verifier.report` (the table row, `verdict.json`),
  `l4.verifier.evidence` (`_generated` restores `covered_by`), `l4.verifier.fixunit` (a noted gap is closed),
  `l4.verifier.conventions` (`e2e_support_files`, new), `l4.verifier.testwriter` (an e2e rule, `TEMPLATE_VERSION` 7),
  `src/l4/templates.lock.json`.
- Spec: L4-VER-067 amended; L4-VER-077 (new); the step-5 row of L4-VER-002 and the `verify.generated` entry of §12.1
  amended; SCN-VER-298..307; change-table row 124.
- Behaviour: a round in the shape of the consumer run raises 2 UI holds in place of 10. A criterion the writer wrongly
  calls `not_testable` is no longer asked about when step 4 covers it; it still needs the judge's pass with an adequate
  test, and the hold comes back when the judge rejects the covering test while another test would pass the criterion. Each writer prompt grows by at most 20,000 characters and a list of paths.
