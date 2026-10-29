## 1. The rule (L4-IMP-087, L4-IMP-024)

- [ ] 1.1 Write the tests first (follow tests/unit/implementer/test_liveness_step.py and test_escalation.py; add
  `tool_calls` (and tokens) knobs to the fake adapter's `Step` in tests/unit/implementer/fake.py so an idle stop can
  report 0 or more tool calls; give SCN-IMP-202's existing test `tool_calls=1` if it flips). Then make design D1 in
  `agent_step` and add `silent` to the limit kind (`l4.agents.base`), with `agent.idle{silent}`. Cases: SCN-IMP-426
  at step level (RoleLimit kind silent, no attempt), SCN-IMP-427, SCN-IMP-428, SCN-IMP-429.

## 2. The limit path (L4-IMP-087, L4-AVL-003/005/006)

- [ ] 2.1 Write the tests first (tests/unit/orchestrator/test_fallback.py, test_escalation.py,
  tests/unit/verifier/test_fixloop_fallback.py, tests/unit/availability/test_fallback.py). Then make sure the `silent`
  kind goes through `switch_profile`/`on_limit` with `availability.default_cooldown`, clears the probe cache, records
  the cool-down and fallback with `kind/reason: silent`, and words the previous-attempt note ("the profile went silent:
  no output for <N>"). Cases: SCN-IMP-426 end to end (events, the step again on profile 2, the next task on profile 2),
  SCN-IMP-430, SCN-IMP-431, a silent fix task moves once, a judge on the same adapter and model is skipped while
  cooling.

## 3. Checks

- [ ] 3.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.
