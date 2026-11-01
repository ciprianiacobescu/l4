## 1. The bounded wait (D1, D2, D3)

- [ ] 1.1 Write the tests first (tests/unit/availability/test_fallback.py): SCN-AVL-33, SCN-AVL-34, SCN-AVL-35 at the
  selection level (a transient hello next to a 24-hour reset, next to a reset 10 minutes away, and alone), a transient
  step timeout (`StepTimedOut`) counted like a hello timeout, and SCN-AVL-36 by the existing auth tests. Then implement
  `_Walk.transient`, its record in `_probe`, `forget`, and the bound in `_nothing_usable`, with its comment.
- [ ] 1.2 Write the test that a park whose skips are transient hellos with `retry_after` 30 minutes after the park is
  not fix-only and that two of them do not stop the plan (tests/unit/yolo/test_yolo_cycle_capacity.py), and update the
  `state.parks` module docstring.

## 2. Checks

- [ ] 2.1 SPEC.md (L4-AVL-013, the fix-only lists of L4-AVL-007 and L4-YOLO-035, SCN-AVL-33..36, row 115), CHANGELOG,
  the availability, yolo and state suites, the docs tests, ruff, `openspec validate transient-retry --strict`.
