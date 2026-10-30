# A local run that cannot sandbox refuses before it touches anything, and one rule says "in a CI job"

## Why

- On macOS (or any host without bubblewrap) a local `l4 run --unit <plan's current unit>` takes the lease, creates the
  worktree and the ledger, and only then fails to select a sandbox (exit 3). The run records `setup_failed`, and the
  next plan step stops the plan for everyone [V, read: orchestrator.py `run_unit_in_worktree` → `build_services` →
  `select_sandbox`; `_run_units` → `record_setup_failures`; cycle.py stops on it]. The message is the Linux-only
  bubblewrap hint.
- Three different "am I in CI" rules are in use: `ci.detect.in_ci` (`GITLAB_CI`, `GITHUB_ACTIONS` or `CI`), inline
  `GITLAB_CI`/`GITHUB_ACTIONS` checks, and a platform-bound `_in_ci(platform)` in forge/base.py. With `CI=true` on a
  laptop the first arms the plan step's job budget while the second treats the machine as local.

## What changes

- `ci.detect.in_ci_job(environ)`: true when `GITLAB_CI` or `GITHUB_ACTIONS` is `"true"`. Every "am I in a CI job"
  decision uses it (the refresh, the plan step's fetch, the continuation, the plan step's budget, the GitLab push
  credential helper, the forge token requirement). The current `in_ci` is renamed `ci_like` and kept only where `CI`
  alone is a deliberate opt-in (the gate environment of L4-SEC-040, the fail-closed sandbox fallbacks of the judges,
  the doctor's tool severity).
- Outside a CI job, `l4 run` (also `--unit`) and `l4 verify` check the sandbox first (`sandbox_refusal`, reusing
  `select_sandbox`), before refs are refreshed, follow-ups run, the plan step runs, a lease is taken or a worktree is
  made. A refusal exits 3 with nothing recorded; on macOS the message names the options (a Linux machine or VM with
  bubblewrap; let CI run it: `l4 ci start`, or `l4 retry` for a halted or escalated unit; `sandbox.mode: container` once it
  exists, and the text names the refused command, `l4 run` or `l4 verify`). In a CI job the
  check stays where it is, so a runner without a sandbox still records `setup_failed`.

## Impact

- Code: `l4.ci.detect`, every site that compares `GITHUB_ACTIONS`/`GITLAB_CI` for a decision, `l4.sandbox.select`,
  `l4.orchestrator` (`run_command`), `l4.verifier.ladder` (`run_verify`).
- Spec: L4-CLI-004 added (the rule), L4-SEC-041 added (the local preflight), L4-YOLO-093 added (a setup failure stops
  the plan, which no requirement said, with the local exception); SCN-CLI-12, SCN-CLI-13,
  SCN-SEC-107 to SCN-SEC-109, SCN-YOLO-255; change-table row 95.
- A local `l4 run` that would have had nothing to do now exits 3 on a host without a sandbox.
- The forge token requirement (`require_token_in_ci`) now follows the one rule: a forge's token is required in any CI job,
  so `forge.type: gitlab` under `GITHUB_ACTIONS` (or the reverse) without a token exits 3, with a message naming the forge.
