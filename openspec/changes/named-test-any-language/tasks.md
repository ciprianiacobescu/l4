## 1. The token and red (L4-IMP-089)

- [ ] 1.1 Write the tests first (tests/unit/implementer/test_named_tests.py, test_red_preexisting_tests.py,
  test_tdd_red.py, test_test_locate.py; tests/unit/verifier/test_base_tests.py with its fake runner for TS JUnit
  reports, test_integrity_superseded.py). Then implement design D1 and D2. Cases: SCN-IMP-439 to SCN-IMP-444, both id
  forms (dotted and plain path), the kept reason of unfreeze's support-file rule unchanged.

## 2. The judge (L4-VER-068)

- [ ] 2.1 Write the test first (the judge prompt tests under tests/unit/verifier; grep `Owner changes`). Then add the
  block of design D3. Case: SCN-VER-253.

## 3. Checks

- [ ] 3.1 Run only the test files you changed or added, once each, then ruff check and ruff format on the changed
  files. Report the counts.
