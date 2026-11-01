## 1. The bounded wait (D1, D2, D3)

- [x] 1.1 Write the tests first (tests/unit/availability/test_fallback.py): SCN-AVL-33, SCN-AVL-34, SCN-AVL-35 at the
  selection level (a transient hello next to a 24-hour reset, next to a reset 10 minutes away, and alone), a transient
  step timeout (`StepTimedOut`) counted like a hello timeout, and SCN-AVL-36 by the existing auth tests. Then implement
  `_Walk.transient`, its record in `_probe`, `forget`, and the bound in `_nothing_usable`, with its comment.
  Result: `_Walk.transient` (recorded in `_probe` for a skip with no limit and class `transient`, dropped by `forget`)
  and the bound in `_nothing_usable`. Tests: SCN-AVL-33, SCN-AVL-34, SCN-AVL-35 (also probed again on the next
  selection), a transient `auth` step next to a 24-hour reset, and SCN-AVL-36 parametrized over `other`, `auth` and no
  class. SCN-AVL-33, SCN-AVL-35 and the transient step failed before the change (they waited for the 24-hour reset);
  SCN-AVL-34 and SCN-AVL-36 guard what does not change. tests/unit/availability: 564 passed.
- [x] 1.2 Write the test that a park whose skips are transient hellos with `retry_after` 30 minutes after the park is
  not fix-only and that two of them do not stop the plan (tests/unit/yolo/test_yolo_cycle_capacity.py), and update the
  `state.parks` module docstring.
  Result: `test_scn_avl_35_two_transient_parks_do_not_stop_the_plan` (fix_parks empty, the plan waits with
  `unit_waiting_capacity`); it passed before the change too, since a future `retry_after` was never fix-only (D3).
  The runbook's capacity section says what 0.4.52 changes.

## 2. Checks

- [ ] 2.1 SPEC.md (L4-AVL-013, the fix-only lists of L4-AVL-007 and L4-YOLO-035, SCN-AVL-33..36, row 115), CHANGELOG,
  the availability, yolo and state suites, the docs tests, ruff, `openspec validate transient-retry --strict`.
