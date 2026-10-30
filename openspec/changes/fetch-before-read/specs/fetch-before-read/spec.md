## Purpose

A person who runs `l4 status`, `plan`, `resume` or `run` on their own computer sees the forge's state, not what the last
manual fetch left, and can still read the local refs on purpose.

## ADDED Requirements

### Requirement: L4-CLI-005 Commands that read a unit's state fetch first, in a CI job or not
`l4 status`, `l4 plan`, `l4 resume`, `l4 run` and `l4 run --dry-run` SHALL fetch the unit branches and the lock refs
with `--prune`, and the plan refs, before they fold anything, once per process, also outside a CI job (with the
credentials `l4 retry` uses for its fetch). A checkout without an `origin` remote SHALL NOT be fetched. With
`--no-fetch` they SHALL fetch nothing and read the local refs. Outside a CI job, a failed fetch SHALL make `l4 status`
warn once (`could not refresh from the forge (<reason>); showing local refs`) and show the local refs, whatever the git
error; it SHALL stop `plan`, `resume`, `run` and `run --dry-run` with the reason and a hint that names `--no-fetch`
(exit 3 when the forge refused the credential, else 1). In a CI job the rules of L4-CLI-003 stay. The sandbox preflight
of L4-SEC-041 SHALL still come before the fetch.

#### Scenario: SCN-CLI-15 (+) A local status sees a remote spec edit
- **GIVEN** a clone whose `origin/l4/openspec/a` is behind the forge, where a person pushed a spec edit
- **WHEN** `l4 status --unit openspec:a` runs outside a CI job
- **THEN** the unit branch was fetched, and the status reads the forge's head

#### Scenario: SCN-CLI-16 (+) `--no-fetch` reads the local refs
- **WHEN** the same command runs with `--no-fetch`
- **THEN** git fetched nothing, and the status reads the local head

#### Scenario: SCN-CLI-17 (−) An offline status shows the local refs
- **WHEN** the fetch fails outside a CI job (no network, a refused credential, an unknown host)
- **THEN** `l4 status` warns once with the reason and exits as it would with the local refs

#### Scenario: SCN-CLI-18 (−) An offline plan or run stops and names `--no-fetch`
- **WHEN** the fetch fails outside a CI job for `l4 plan`, `l4 resume`, `l4 run --unit`, or `l4 run --dry-run`
- **THEN** the command exits 1 (3 for a refused credential) before it folds anything, and the message names the reason
  and `--no-fetch`

#### Scenario: SCN-CLI-19 (+) A local run fetches after its sandbox preflight
- **WHEN** a local `l4 run --unit` cannot sandbox
- **THEN** it refuses (L4-SEC-041) and fetched nothing; when it can, it fetches before it reads the unit

## MODIFIED Requirements

### Requirement: L4-OPS-014 (amendment, the last sentence)
The sentence "`l4 run --unit` outside CI does not fetch, so a stale ref can miss a remote spec edit; `l4 retry`
fetches" SHALL be replaced: `l4 run --unit` fetches before it reads the unit (L4-CLI-005), unless `--no-fetch`.

#### Scenario: SCN-CLI-20 (+) A local run takes a spec edit pushed from elsewhere
- **GIVEN** a person pushed a spec edit to the unit branch from another computer
- **WHEN** `l4 run --unit` runs on a computer whose tracking ref is behind
- **THEN** the run fetches, sees the edit, and records `unit.retried{reason: "spec edited", by: "push"}`

### Requirement: SCN-CLI-12 (amendment, CI=true alone)
With `CI=true` alone the refresh SHALL fetch as outside a CI job (the failure rules of L4-CLI-005), not as a job does.

#### Scenario: SCN-CLI-12 (amended) CI=true alone is not a CI job
- **GIVEN** an environment with `CI=true` and neither `GITLAB_CI` nor `GITHUB_ACTIONS`
- **WHEN** the harness asks whether it runs in a CI job and whether the environment is CI-like
- **THEN** `in_ci_job` is false and `ci_like` is true; the plan step has no job budget, the refresh fetches with the
  failure rules of a person's computer and the sandbox preflight of L4-SEC-041 applies, while the gates still get `CI`
  (L4-SEC-040)
