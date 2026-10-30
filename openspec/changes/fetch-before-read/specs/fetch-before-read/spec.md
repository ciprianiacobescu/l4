## Purpose

A person who runs `l4 status`, `plan`, `resume`, `run` or `archive` on their own computer sees the forge's state, not what the last
manual fetch left, and can still read the local refs on purpose.

## ADDED Requirements

### Requirement: L4-CLI-005 Commands that read a unit's state fetch first, in a CI job or not
`l4 status`, `l4 plan`, `l4 resume`, `l4 run`, `l4 run --dry-run` and `l4 archive` SHALL fetch the unit branches and the
lock refs with `--prune`, and the plan refs, before they fold anything, once per process, also outside a CI job (with
the credentials `l4 retry` uses for its fetch). A checkout without an `origin` remote SHALL NOT be fetched. With
`--no-fetch` they SHALL fetch nothing for the state and read the local refs (`Read the local refs for the state; a run's
worktree still fetches the unit.`): the flag does not reach the worktree of `l4 run`, `l4 resume` and `l4 archive`,
which fetches the base branch and the unit refs before it cuts the branch it works on. A CI job SHALL NOT use
`--no-fetch` (exit 2: `--no-fetch is for a person's computer: a CI job must not read stale refs (L4-CLI-003)`).
Outside a CI job, a failed fetch SHALL make `l4 status` warn once (`could not refresh from the forge (<reason>); showing
local refs`) and show the local refs, whatever the git error, and `l4 status` SHALL give up on the fetch after 15
seconds; it SHALL stop `plan`, `resume`, `run`, `run --dry-run` and `archive` with the reason (exit 3 when the forge
refused the credential, else 1; a refused credential names `forge.token_env` when that variable is set, because git
then uses it instead of the person's credential helper). The hint that ends the message depends on the command:
`plan` and `run --dry-run`, which make no worktree, say `pass --no-fetch to read the local refs`; `run` and `resume`
say that a run needs the forge (its worktree fetches the unit) and name `l4 status --no-fetch` to read the local state;
`archive` says the same about its worktree (it fetches the base branch). In a CI job the rules of L4-CLI-003 stay. The
sandbox preflight of L4-SEC-041 SHALL still come before the fetch.

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

#### Scenario: SCN-CLI-18 (−) An offline plan, dry run, run, resume or archive stops and says how to go on
- **WHEN** the fetch fails outside a CI job for `l4 plan`, `l4 resume`, `l4 run --unit`, `l4 run --dry-run` or
  `l4 archive`
- **THEN** the command exits 1 (3 for a refused credential) before it folds anything, and the message names the reason
  and the way on: `--no-fetch` for `plan` and `run --dry-run`; for `run`, `resume` and `archive` that the command needs
  the forge (its worktree fetches) and that `l4 status --no-fetch` reads the local state

#### Scenario: SCN-CLI-21 (−) `--no-fetch` in a CI job is refused
- **WHEN** a command with `--no-fetch` runs in a CI job
- **THEN** it exits 2 with `--no-fetch is for a person's computer: a CI job must not read stale refs (L4-CLI-003)`

#### Scenario: SCN-CLI-22 (−) A refused credential names the token variable
- **GIVEN** `forge.token_env` is set in the environment
- **WHEN** the fetch is refused outside a CI job
- **THEN** the exit-3 message says that variable is set, so git uses it instead of the credential helper, and to check
  or unset it

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
