## 1. The forge call and the command (L4-OPS-024)

- [ ] 1.1 Write the tests first (tests/unit/forge/test_start_run.py, test_dispatch_continuation.py,
  test_gitlab_continuation.py; the fakes `FakeGitHub` in _github_helpers.py with `queued_runs` and the run listing, and
  `RefAwareGitLab`; the CLI spec test that every command has a §2.1 row). Then implement design D1 and D2, including a
  GitLab running pipeline blocking the start. Cases: SCN-OPS-46 to SCN-OPS-50.

## 2. Checks

- [ ] 2.1 Run only the test files you changed or added, once each, then ruff check and ruff format on the changed
  files. Report the counts.
