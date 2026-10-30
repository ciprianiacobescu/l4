## 1. One rule (L4-CLI-004)

- [x] 1.1 Write the tests first (tests/unit/sandbox/test_env.py SCN-SEC-103, tests/unit/yolo/test_yolo_judge_sandbox.py,
  tests/unit/vcs/test_refresh.py; a new contract test). Then implement design D1. Cases: SCN-CLI-12, SCN-CLI-13; the
  existing sandbox-env and judge-fallback behaviour unchanged.
  Result: `l4.ci.detect` now has `in_ci_job` (GITLAB_CI or GITHUB_ACTIONS is `true`) and `ci_like` (the old `in_ci`:
  also `CI=true`). `in_ci_job` is used by the refresh, the plan step's fetch, the continuation and its info line, the
  plan step's budget, the gate-env INFO line of `_log_gate_env`, the GitLab push credential helper and
  `require_token_in_ci`; `ci_like` stays in sandbox/env.py, the judge fallbacks (commands.py, review_worktree.py) and
  the doctor's gates and tools checks. Tests: tests/unit/ci/test_ci_detect.py (SCN-CLI-12), the new
  tests/unit/ci/test_ci_rule.py (SCN-CLI-13: an AST walk over src/l4 lists each comparison of the two variables
  against an allowlist of the "which CI" sites, and fails on a stale entry), plus cases in test_refresh.py,
  test_env.py, test_yolo_judge_sandbox.py and test_make_forge_platform.py. Deviation: `require_token_in_ci` also
  returns early for the `local` forge, because the old platform-bound check was false for it and `in_ci_job` is not.

## 2. The preflight (L4-SEC-041, L4-YOLO-093)

- [x] 2.1 Write the tests first (tests/unit/orchestrator/test_run_unit.py patches `l4.sandbox.select.resolve_tool`;
  tests/unit/state/test_resume.py must stay green; tests/unit/yolo/test_yolo_setup_failed.py;
  tests/unit/sandbox/test_select.py). Then implement design D2. Cases: SCN-SEC-107 to SCN-SEC-109, SCN-YOLO-255, Linux
  keeps `BWRAP_HINT`, `mode: none` with `allow_none` runs.
  Result: `sandbox_refusal(cfg, environ, repo, platform=None)` in `l4.sandbox.select` takes the `SandboxCfg` (as
  `select_sandbox` does), returns None when `select_sandbox` would succeed, else its text; on darwin the Linux-only half
  of the bubblewrap hint is replaced by the three ways out; Linux keeps `BWRAP_HINT`. `run_command` (after
  `preflight_run_config`, before the refresh, follow-ups, plan step, lease, worktree) and `run_verify` (after its config
  load, before the unit is read) call it when not `in_ci_job`. Tests: test_select.py, test_run_unit.py (SCN-SEC-107 to
  SCN-SEC-109, the CI path of SCN-YOLO-255, `CI=true` alone is local, `mode: none` + `allow_none` runs),
  test_yolo_setup_failed.py (SCN-YOLO-255 at the plan level). Deviations: (1) a refusal is logged as an error and
  returned as `CommandResult(3)` instead of raising, because tests/unit/state/test_resume.py (which must stay green)
  expects `run_command` to return exit 3 for a sandbox-less config; the CLI exit code and message are the same, and no
  ledger, lease, worktree or ref is touched. (2) `platform` defaults to None and is read as `sys.platform` at call time,
  so a test can patch it. (3) `mode: none` without `allow_none` is also refused up front (the run would refuse it at
  `build_services` after the lease and ledger); with `allow_none` it selects nothing and warns nothing here.

- [x] 2.2 Review fixes
  Result: (1) `require_token_in_ci` applies to any forge under any CI job (`forge.type: gitlab` with `GITHUB_ACTIONS`,
  github under `GITLAB_CI`, and `l4 plan --sweep`, which calls it): kept, and listed here as a deviation from the old
  per-platform check; L4-CLI-004 and the proposal say it, and the message names the forge ("the GitLab forge needs ...",
  "the GitHub forge needs ..."), tested for all four pairs. (2) The macOS text says `l4 ci start`, and `l4 retry` for a
  halted or escalated unit, and names the refused command (`sandbox_refusal(..., command=)`: `l4 run` or `l4 verify`);
  proposal, design and spec follow. (3) The SCN-CLI-13 allowlist is keyed by (file, enclosing function) with the expected
  number of reads, and the scan finds `.get`, `os.getenv`, `getenv`, subscripts, `in` / `not in` and truthiness tests;
  synthetic sources show each form is found and that an injected read, in an allowlisted file too, fails. (4) L4-CLI-004
  names the doctor's tool and gate severity as an opt-in; the false "L4-SEC-005 amended" claim is gone from the proposal.
  (5) New tests: the whole `run_command` chain in a `GITHUB_ACTIONS` job with an active plan and no bwrap records
  `unit.setup_failed` and the next step stops the plan (`setup_failed`), and the same run locally returns exit 3 with the
  plan ledger untouched (test_yolo_cycle_run.py); `CI=true` alone gives the plan step no budget
  (test_plan_step_budget.py); the test_yolo_setup_failed.py docstring now says the local check returns.

## 3. Checks

- [x] 3.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.
  Result: ruff check and format are clean on every changed file. Counts: task 1.1 files 102 passed; task 2.1 files 81
  passed; task 2.2 files 84 passed in one run (test_ci_rule, test_make_forge_platform, test_select,
  test_plan_step_budget, test_yolo_setup_failed, test_yolo_cycle_run; one budget test fixed and rerun, 1 passed) and
  test_run_unit 26 passed, run once separately. The whole suite is CI's.
