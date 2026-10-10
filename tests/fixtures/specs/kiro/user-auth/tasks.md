# Implementation Plan

- [ ] 1. Sign-in
  - [ ] 1.1 Add the login endpoint
    - _Requirements: 1.1_
  - [ ] 1.2 Reject wrong passwords
    - _Requirements: 1.2_
  - [ ]* 1.3 Add a property test for the endpoint
    - _Requirements: 1.1, 1.2_
- [ ] 2. Sign-out
  - [ ] 2.1 Add the logout endpoint
    - _Requirements: 2.1, 2.2_
  - [ ] 2.2 [docs] Document the sign-out flow

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["2.1", "1.1"]}, {"id": 1, "tasks": ["1.2"]}]}
```
