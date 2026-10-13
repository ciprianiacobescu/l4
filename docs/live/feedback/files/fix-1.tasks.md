# Implementation Plan

- [x] 1. Fix the findings of the verifier
  - [x] 1.1 [chore] Feedback FB-001 (refactor): Move the on_hand validation into a small helper, _require_non_negative(o (F-b7a3ac18)
  - [x] 1.2 Feedback FB-002 (config): The low-stock threshold 5 is hard-coded; read it from LOW_STOCK_THRESHOL (F-0499efa7; C-357020b8, C-ea291e36)
    - _Requirements: 2.1, 3.1_

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1", "1.2"]}]}
```
