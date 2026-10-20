## Purpose

A GitHub run that the pin guard stops, because it runs a copy of the workflow that is not the base's (a scheduled
run on a default branch that is not the base, or a push to a unit branch whose copy pins an older harness), starts the
base's own workflow once, so the schedule keeps moving a plan when the base is not the default branch.

## ADDED Requirements

### Requirement: L4-IMP-072 A run on a stale copy of the workflow relays to the base
In GitHub Actions, when `l4 run` does no work because the running harness is not the base's pin (L4-ADO-005), it SHALL
dispatch one `workflow_dispatch` of `l4.yml` on `forge.base_branch`, and print one line that says so, after the
existing warning. It MUST NOT dispatch when any of these holds:
- the run itself is on the base branch (`GITHUB_REF_NAME` equals the base);
- a run of `l4.yml` other than this one is `queued`, `pending`, `waiting`, `requested` or `in_progress` on the base;
- the base has no possible work.
The base has possible work when a delivery plan is `active` or `waiting`, when a unit has a next step, when a unit's
phase is one the running harness does not know, or when reading any of these fails. `l4 plan --sweep` MUST NOT
dispatch. A token that may not dispatch (no token, 401, 403, 404) MUST be a line that names `gh workflow run l4.yml
--ref <base>`, never a failure. The exit code stays 0. `outcome.json` SHALL record `relay` with the answer. Outside
GitHub Actions nothing changes: GitLab's `l4 sweep` schedule targets the base, and the pin guard does not apply there.

#### Scenario: SCN-IMP-350 (+) A scheduled run on the default branch relays to the base
- **GIVEN** a base `staging` whose `l4.yml` pins commit B, a default branch `main` whose copy installed commit A
  (`GITHUB_REF_NAME=main`), an active plan on `staging`, and no other run of `l4.yml` on `staging`
- **WHEN** `l4 run` runs in that scheduled job
- **THEN** it does no work, prints the `::warning::` of L4-ADO-005, then `::notice::l4 relayed this run to staging:
  started l4.yml on staging, which runs the base's pin`; the forge receives one `workflow_dispatch` of `l4.yml` on
  `staging`; `outcome.json` has `relay: dispatched`; the exit is 0

#### Scenario: SCN-IMP-351 (−) A run already queued or running on the base is not doubled
- **GIVEN** the job of SCN-IMP-350, and a run of `l4.yml` on `staging` with status `pending` (or `queued`, or
  `in_progress`)
- **WHEN** `l4 run` runs
- **THEN** no dispatch is sent, the line says `not relayed: a run of l4.yml is already queued or running on staging`,
  and `relay` is `already_running`

#### Scenario: SCN-IMP-352 (−) A mismatch on the base itself does not relay
- **GIVEN** a run with `GITHUB_REF_NAME=staging` whose running harness differs from `staging`'s pin
- **WHEN** `l4 run` runs
- **THEN** only the existing warning is printed, nothing is dispatched, and `relay` is `on_base`

#### Scenario: SCN-IMP-353 (−) A base with no possible work is not relayed
- **GIVEN** the job of SCN-IMP-350 with no plan that is `active` or `waiting` and no unit with a next step
- **WHEN** `l4 run` runs
- **THEN** nothing is dispatched, the line says `not relayed: staging has no active or waiting plan and no unit with a
  next step`, and `relay` is `no_work`

#### Scenario: SCN-IMP-354 (+) A base state the running harness cannot read is relayed
- **GIVEN** the job of SCN-IMP-353, but a unit's ledger holds a phase this harness does not know (or the fold raises)
- **WHEN** `l4 run` runs
- **THEN** one dispatch is sent and `relay` is `dispatched`

#### Scenario: SCN-IMP-355 (−) A token that may not dispatch names the command
- **GIVEN** the job of SCN-IMP-350, and a forge that answers the dispatch with 403
- **WHEN** `l4 run` runs
- **THEN** the line says `not relayed: the token may not start a run on staging; start one with: gh workflow run l4.yml
  --ref staging`, `relay` is `refused`, and the exit is 0

#### Scenario: SCN-IMP-356 (+) Outside GitHub Actions nothing changes
- **GIVEN** a GitLab job (`GITLAB_CI=true`, no `GITHUB_ACTIONS`) and the same pins
- **WHEN** `l4 run` runs
- **THEN** the pin guard is skipped, the run works as before, nothing is relayed, and `outcome.json` has no `relay`
