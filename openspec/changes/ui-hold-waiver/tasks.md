## 1. A stable hold and the waiver (L4-VER-067)

- [ ] 1.1 Write the tests first (tests/unit/verifier/test_ui_step.py `crit`/`event`, test_hold_verdicts.py,
  test_verdicts.py; flows in test_ui_flow.py with `web_repo` and `edit_questions_on_origin`). Then implement design D1
  to D3. Cases: SCN-VER-247 to SCN-VER-252; `unclosed_holds` skips `waived`; amend test_ui_step.py's text test (no
  status) and test_ui_flow.py's `(UNKNOWN, "accepted")` regeneration case, which becomes `waived` when only a
  non-tracing file changed; a flow: round 1 hold accepted, round 2 records `waived`, raises no question and exits 0.

## 2. Checks

- [ ] 2.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.
