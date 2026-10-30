# Design: local-run-preflight

## D1 The rule (do this first)

`in_ci_job(environ) -> bool` in `l4.ci.detect`: `environ.get("GITLAB_CI") == "true" or environ.get("GITHUB_ACTIONS")
== "true"`. Move to it: vcs/refresh.py (the CI-only fetch), yolo/cycle.py (the plan step's fetch), orchestrator.py's
continuation and its info line, the plan step budget's `running_in_ci` (orchestrator.py), forge/gitlab.py's push
credential helper, and `forge/base.py` `_in_ci(platform)` (`require_token_in_ci`). Rename `in_ci` to `ci_like` and keep
it at sandbox/env.py (L4-SEC-040), the judge's fail-closed sandbox fallbacks (yolo/commands.py, review_worktree.py,
SCN-YOLO-61), and doctor/checks_tools.py, checks_gates.py. Sites that ask *which* CI (base.py's platform, cancel,
progress, exitcodes, pin_guard, relay, step_summary, checks_ci, state/environment, github, pushfail, pushurl) stay. A
contract test lists every raw comparison of `GITHUB_ACTIONS`/`GITLAB_CI` outside `ci/detect.py` against an allowlist.

## D2 The preflight

`sandbox_refusal(cfg, environ, repo, platform=sys.platform) -> str | None` in `l4.sandbox.select`: None for
`sandbox.mode: none`; else calls `select_sandbox(..., events=None)` and returns the refusal text on
`SandboxUnavailable`, with a darwin text naming the three options (Linux machine or VM with bubblewrap; CI: `l4 ci start`, or
`l4 retry` for a halted or escalated unit, naming the refused command; `sandbox.mode: container` once it ships); Linux keeps `BWRAP_HINT`. Call it when not `in_ci_job` in
`run_command` right after `preflight_run_config` (before `refresh_refs`, follow-ups, the plan step, any lease) and in
`run_verify` after its config load: exit 3 with the text, nothing recorded. Not in `run_unit_in_worktree` (a raise
there lands in `not_started` after the plan charge). `retry` and `resume` need nothing. In a CI job nothing changes.

## D3 Not changed

`l4 simulate` (mode none + allow_none) runs; the CI path still records `setup_failed`, which stops the plan.
