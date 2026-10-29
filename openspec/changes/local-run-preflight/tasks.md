## 1. One rule (L4-CLI-004)

- [ ] 1.1 Write the tests first (tests/unit/sandbox/test_env.py SCN-SEC-103, tests/unit/yolo/test_yolo_judge_sandbox.py,
  tests/unit/vcs/test_refresh.py; a new contract test). Then implement design D1. Cases: SCN-CLI-12, SCN-CLI-13; the
  existing sandbox-env and judge-fallback behaviour unchanged.

## 2. The preflight (L4-SEC-041, L4-YOLO-093)

- [ ] 2.1 Write the tests first (tests/unit/orchestrator/test_run_unit.py patches `l4.sandbox.select.resolve_tool`;
  tests/unit/state/test_resume.py must stay green; tests/unit/yolo/test_yolo_setup_failed.py;
  tests/unit/sandbox/test_select.py). Then implement design D2. Cases: SCN-SEC-107 to SCN-SEC-109, SCN-YOLO-255, Linux
  keeps `BWRAP_HINT`, `mode: none` with `allow_none` runs.

## 3. Checks

- [ ] 3.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.
