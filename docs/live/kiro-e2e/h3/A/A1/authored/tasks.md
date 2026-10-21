# Implementation Plan

- [ ] 1. Implement Cart.small_order_surcharge() method
  - [ ] 1.1. Add Cart.small_order_surcharge() method with unit tests
    - _Requirements: 2.1, 2.2_

- [ ] 2. Implement surcharge rule module
  - [ ] 2.1. Create src/pricing/surcharge.py with small_order_surcharge function and unit tests
    - _Requirements: 1.1, 1.2_
  - [ ] 2.2. Add unit test for 19.99 edge case
    - _Requirements: 1.3_
  - [ ]* 2.3. Add property-based tests for surcharge rule
    - _Requirements: 1.1, 1.2_

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["2.1", "2.2", "2.3"]}, {"id": 1, "tasks": ["1.1"]}]}
```
