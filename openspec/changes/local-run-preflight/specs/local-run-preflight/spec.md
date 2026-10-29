## ADDED Requirements

### Requirement: L4-CLI-004 One rule says whether the harness runs in a CI job
The harness SHALL decide "this is a CI job" only from `GITLAB_CI` or `GITHUB_ACTIONS` set to `true`. `CI` alone SHALL
count only where a requirement makes it an opt-in (L4-SEC-040, the judges' fail-closed sandbox fallback).

### Requirement: L4-SEC-041 A local run that cannot sandbox refuses before it touches anything
Outside a CI job, `l4 run` and `l4 verify` SHALL check that a sandbox can be selected before they refresh refs, run
follow-ups, take a plan step, take a lease or make a worktree, and SHALL exit 3 with nothing recorded when none can be;
on macOS the message SHALL name the ways out.

### Requirement: L4-YOLO-093 A unit whose setup fails stops its plan, not a local refusal
A plan SHALL stop when its current unit records `unit.setup_failed` in a CI job. A local refusal of L4-SEC-041 SHALL
NOT record it.

#### Scenario: SCN-CLI-12 (−) CI=true alone is not a CI job
- **WHEN** only `CI=true` is set
- **THEN** `in_ci_job` is false and `ci_like` is true

#### Scenario: SCN-CLI-13 (+) no decision reads the CI variables outside the rule
- **WHEN** the source is searched for comparisons of `GITHUB_ACTIONS` or `GITLAB_CI`
- **THEN** each is in `ci/detect.py` or on the allowlist of sites that ask which CI runs

#### Scenario: SCN-SEC-107 (−) a local run on a host without a sandbox touches nothing
- **WHEN** `l4 run --unit <the plan's current unit>` runs locally without bubblewrap
- **THEN** it exits 3 before any lease, worktree, ledger line, follow-up or plan event, and the plan is not stopped

#### Scenario: SCN-SEC-108 (+) the macOS refusal names the ways out
- **WHEN** the same run is on macOS
- **THEN** the message names a Linux machine or VM with bubblewrap, `l4 retry` / `l4 ci start`, and the container mode

#### Scenario: SCN-SEC-109 (+) `l4 verify` refuses the same way
- **WHEN** `l4 verify` runs locally without a sandbox
- **THEN** it exits 3 before it touches the unit

#### Scenario: SCN-YOLO-255 (+) in a CI job a setup failure still stops the plan
- **WHEN** the same run is in a CI job (`GITHUB_ACTIONS=true`) without a sandbox
- **THEN** `unit.setup_failed` is recorded and the plan stops, as before
