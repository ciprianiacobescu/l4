## 1. A stable hold and the waiver (L4-VER-067)

- [x] 1.1 Write the tests first (tests/unit/verifier/test_ui_step.py `crit`/`event`, test_hold_verdicts.py,
  test_verdicts.py; flows in test_ui_flow.py with `web_repo` and `edit_questions_on_origin`). Then implement design D1
  to D3. Cases: SCN-VER-247 to SCN-VER-252; `unclosed_holds` skips `waived`; amend test_ui_step.py's text test (no
  status) and test_ui_flow.py's `(UNKNOWN, "accepted")` regeneration case, which becomes `waived` when only a
  non-tracing file changed; a flow: round 1 hold accepted, round 2 records `waived`, raises no question and exits 0.

  Result: D1 to D3 built as designed. `ui_step` gets `ui_hold_text` (no status), `ui_hold_binding`, `ui_hold_views` and
  `ui_waivers`; `unclosed_holds` skips `waived`; `_generate_step` takes `events`, records `verify.generated{waived, by,
  attempts: 0}` for each waived gap, keeps the minor gap finding ("waived by Q-…") and calls the writer only for the
  rest (when none is left it records the step `ok` without calling `generate_ui_tests`). `question.raised` of a UI hold
  carries `criterion` and `criterion_sha256`; its accept is bound by the `hold_views` sha, which `judge_body` now merges
  into instead of replacing. `GenStatus` has `waived` and `GeneratedOutcome` has `by`. Closest-correct choices: `by` is the
  answered question (Q-…); a hold accept written before this change has no binding, so it waives until a reject, a void
  or a failing tracing test; an accept of the criterion itself is bound to its text only (as today), so a tracing-file
  change ends the waiver of a hold's accept, not of a criterion verdict's; the binding leaves out the audit and generated
  tests (a round writes them after the accept); `fixunit` treats a waived gap as closed so `fix_minor` spawns no fix unit
  for it. Tests: test_ui_step.py 29, test_hold_verdicts.py 57, test_verdicts.py 30 (unchanged), test_ui_flow.py 9,
  test_fixunit.py 41, all passing.

## 2. Checks

- [ ] 2.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.
