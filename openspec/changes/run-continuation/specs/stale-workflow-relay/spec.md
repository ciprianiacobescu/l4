## Purpose

A GitHub run that the pin guard stops, because it runs a copy of the workflow that is not the base's (a scheduled
run on a default branch that is not the base, or a push to a unit branch whose copy pins an older harness), starts the
base's own workflow once, before it reads the configuration, so the schedule keeps moving a plan when the base is not
the default branch. The base's own run says when the default branch's copy is behind.

## ADDED Requirements

### Requirement: L4-IMP-072 A run on a stale copy of the workflow relays to the base
In GitHub Actions, on any ref other than the base branch (`GITHUB_REF_NAME` differs from the base), `l4 doctor --ci`,
`l4 plan --sweep`, `l4 run` and `l4 status` SHALL check the pin (L4-ADO-005) before they load the configuration. The
check reads only the job environment (`GITHUB_*`, `L4_BASE_BRANCH`), the checked-out `.github/workflows/l4.yml`, and a
few keys of `.l4/config.yaml` read without the schema, with the strict loader's YAML 1.2 rules (`harness.delivery`,
`harness.repository`, `forge.type`, `forge.base_branch`, `forge.branch_prefix`, `forge.token_env`, `spec.openspec.root`,
`spec.kiro.root`; a scalar is read as a string, anything else is ignored). So a configuration key that the running
harness does not know cannot stop it. When `harness.delivery` cannot be read, a setup-action pin in the checked-out
workflow means `action`. On a mismatch, every one of these commands prints the existing warning, does no work and exits
0 before the configuration is loaded, and the first of `l4 doctor --ci`, `l4 plan --sweep` and `l4 run` in the job
relays: it dispatches one `workflow_dispatch` of `l4.yml` on the base and prints one line that says what it did. A later
command in the same job MUST NOT dispatch again; it trusts the job's marker only when the marker's run id, run attempt
and job equal the current ones. `l4 status` never relays. On the base branch itself nothing moves before the
configuration: a schema error stays exit 2, and a mismatch is reported as today. The relay MUST NOT dispatch when any of
these holds:
- a run of `l4.yml` other than this one is `queued`, `pending`, `waiting`, `requested` or `in_progress` on the base;
- the base has no possible work.
The base has possible work, read with git only, when a delivery plan ref is `active` or `waiting`, when a plan ref
cannot be read or folded, when a branch under the unit prefix exists on origin, when the checked-out base holds a unit
folder (a `tasks.md` under the OpenSpec changes, not in their archive, or under the Kiro specs), or when reading any of
these fails. A token that may not dispatch (no token, 401, 403, 404) MUST be a line that names `gh workflow run l4.yml
--ref <base>`, never a failure. `outcome.json` of `l4 run` SHALL record `relay` with the job's answer. Outside GitHub
Actions nothing changes: GitLab's `l4 sweep` schedule targets the base, and the pin guard does not apply there.

#### Scenario: SCN-IMP-350 (+) A scheduled run on the default branch relays to the base
- **GIVEN** a base `staging` whose `l4.yml` pins commit B, a default branch `main` whose copy installed commit A
  (`GITHUB_REF_NAME=main`), an active plan on `staging`, and no other run of `l4.yml` on `staging`
- **WHEN** the job's first harness step, `l4 doctor --ci`, runs
- **THEN** it prints the `::warning::` of L4-ADO-005, then `::notice::l4 relayed this run to staging: started l4.yml on
  staging, which runs the base's pin`; the forge receives one `workflow_dispatch` of `l4.yml` on `staging`; the job's
  `l4 run` does no work, exits 0 and its `outcome.json` has `relay: dispatched`

#### Scenario: SCN-IMP-351 (−) A run already queued or running on the base is not doubled
- **GIVEN** the job of SCN-IMP-350, and a run of `l4.yml` on `staging` with status `pending` (or `queued`, or
  `in_progress`)
- **WHEN** the job's first harness step runs
- **THEN** no dispatch is sent, the line says `not relayed: a run of l4.yml is already queued or running on staging`,
  and `relay` is `already_running`

#### Scenario: SCN-IMP-352 (−) A mismatch on the base itself does not relay
- **GIVEN** a run with `GITHUB_REF_NAME=staging` whose running harness differs from `staging`'s pin
- **WHEN** `l4 run` runs
- **THEN** the configuration is loaded first, as today; then only the existing warning is printed, nothing is
  dispatched, and `relay` is `on_base`

#### Scenario: SCN-IMP-353 (−) A base with no possible work is not relayed
- **GIVEN** the job of SCN-IMP-350 with no plan ref, no branch under the unit prefix and no unit folder on `staging`
- **WHEN** the job's first harness step runs
- **THEN** nothing is dispatched, the line says `not relayed: staging has no active or waiting plan, no unit branch and
  no unit folder`, and `relay` is `no_work`

#### Scenario: SCN-IMP-354 (+) A plan ref that cannot be read is work
- **GIVEN** the job of SCN-IMP-353, but one plan ref whose ledger does not parse
- **WHEN** the job's first harness step runs
- **THEN** one dispatch is sent and `relay` is `dispatched`

#### Scenario: SCN-IMP-355 (−) A token that may not dispatch names the command
- **GIVEN** the job of SCN-IMP-350, and a forge that answers the dispatch with 403
- **WHEN** the job's first harness step runs
- **THEN** the line says `not relayed: the token may not start a run on staging; start one with: gh workflow run l4.yml
  --ref staging`, `relay` is `refused`, and every step exits 0
  Every other line that gives no relay names its cause and the same command: a failure of the forge's call
  (`not relayed: <first line>; start one with: gh workflow run l4.yml --ref staging`), a forge key of the configuration
  that is not valid (the line names the first such key), and a missing token (`relay` is `refused`; the line names
  `forge.token_env`, `L4_FORGE_TOKEN` by default, as not set in this job and says that the job's environment must allow
  the default branch). The configured `forge.token_env` value is redacted from these lines and the log. The relay reads
  the file `--config` names, as the command does, and ignores a recorded `relay` answer that is not one of the seven.

#### Scenario: SCN-IMP-356 (+) Outside GitHub Actions nothing changes
- **GIVEN** a GitLab job (`GITLAB_CI=true`, no `GITHUB_ACTIONS`) and the same pins
- **WHEN** `l4 run` runs
- **THEN** the pin guard is skipped, the run works as before, nothing is relayed, and `outcome.json` has no `relay`

#### Scenario: SCN-IMP-369 (+) A configuration key the running harness does not know does not defeat the relay
- **GIVEN** the job of SCN-IMP-350, and a `.l4/config.yaml` on `staging` with a key that the strict schema of commit A
  rejects
- **WHEN** the job runs `l4 doctor --ci`, `l4 plan --sweep` and `l4 run` in that order
- **THEN** `l4 doctor --ci` relays and exits 0 before it loads the configuration, running none of its checks; `l4 plan
  --sweep`, `l4 run` and `l4 status` stop before the load and exit 0; exactly one dispatch is sent

#### Scenario: SCN-IMP-370 (+) One relay per job
- **GIVEN** the job of SCN-IMP-350
- **WHEN** `l4 doctor --ci`, `l4 plan --sweep` and `l4 run` each run in it
- **THEN** only `l4 doctor --ci` calls the forge; the two later commands print `l4: relayed earlier in this job
  (dispatched)` and send nothing; a marker left by another run id, run attempt or job is ignored, and the command
  relays

#### Scenario: SCN-IMP-371 (+) A unit branch or a unit folder is work
- **GIVEN** the job of SCN-IMP-353, and in one case a branch `l4/openspec/add-x` on origin, in another an
  `openspec/changes/add-x/tasks.md` on `staging`
- **WHEN** the job's first harness step runs
- **THEN** each case sends one dispatch; an `openspec/changes/archive/old/tasks.md` alone is not work

#### Scenario: SCN-IMP-381 (−) On the base a configuration error stays exit 2
- **GIVEN** `GITHUB_REF_NAME=staging` (the base), a running harness that differs from `staging`'s pin, and a key in
  `.l4/config.yaml` that the strict schema rejects
- **WHEN** `l4 doctor --ci` runs
- **THEN** it exits 2 with the schema error, and nothing is relayed

#### Scenario: SCN-IMP-382 (+) The stopped job's status step is not red
- **GIVEN** the job of SCN-IMP-369
- **WHEN** the template's `status` step runs `l4 status`
- **THEN** it prints the warning of L4-ADO-005, makes no forge call and exits 0

#### Scenario: SCN-IMP-384 (+) The lenient read keeps YAML 1.2 values and finds the delivery in the workflow
- **GIVEN** a `.l4/config.yaml` with `forge: {base_branch: on, token_env: L4_TOKEN, type: github}` (`on` unquoted), an
  unknown key, and no `harness.delivery`, and a checked-out `l4.yml` with a setup-action `uses:` pin
- **WHEN** the early pin check reads it
- **THEN** the base is the string `on`, the token comes from `L4_TOKEN`, the delivery is `action`, and the unknown key
  is ignored; a symlinked `.l4/config.yaml` or one over 1 MB is not read, and nothing stops early

### Requirement: L4-IMP-074 The base's run names a default-branch copy that is behind
In GitHub Actions with `harness.delivery: action`, a run of `l4 run` on the base branch SHALL read the default
branch's name from the event payload (`repository.default_branch`). When it is not the base, it SHALL read
`origin/<default>:.github/workflows/l4.yml`. When that file is missing, it SHALL print one `::warning::` saying that no
scheduled run starts from the default branch, with the copy step. When its pin differs from the base's, it SHALL print
one `::warning::` that names the default branch, both short shas, the release of that copy when its `uses:` line has a
`# vX.Y.Z` comment (a comment that is not a version is ignored), and the step: copy `.github/workflows/l4.yml` to the
default branch once, or promote the base. Versions MUST be compared as numbers (0.4.9 is older than 0.4.19). With a
release older than 0.4.19, the warning MUST say that the default branch's scheduled runs cannot relay to the base; with
no release known, it MUST say so conditionally (`if that copy is older than 0.4.19, its scheduled runs cannot relay`).
With the same pin, an unknown default branch, the default branch as base, or another delivery, nothing is printed.

#### Scenario: SCN-IMP-375 (+) The base's run warns about an older default-branch copy
- **GIVEN** a run on `staging` whose pin is B (v0.4.19), and `origin/main:.github/workflows/l4.yml` pinning A with the
  comment `# v0.4.18`, with `repository.default_branch: main` in the event payload
- **WHEN** `l4 run` runs on `staging`
- **THEN** it prints one `::warning::` that names `main`, A's and B's short shas, `v0.4.18`, says that `main`'s
  scheduled
  runs cannot relay to `staging`, and names the copy step; the run then works as usual

#### Scenario: SCN-IMP-376 (−) No warning when the copy is current or the default branch is unknown
- **GIVEN** the run of SCN-IMP-375 with `main`'s copy pinning B; in a second case no `repository.default_branch` in the
  payload; in a third `harness.delivery: vendored`
- **WHEN** `l4 run` runs on `staging`
- **THEN** no such warning is printed

#### Scenario: SCN-IMP-383 (+) An unknown release, a numeric compare, a branch comment and a missing copy
- **GIVEN** the run of SCN-IMP-375, and in turn: `main`'s copy pins A with no comment (the copy form, or no ref given);
  with `# v0.4.9`; with `# main`; and `main` with no `.github/workflows/l4.yml`
- **WHEN** `l4 run` runs on `staging`
- **THEN** the first warning says `if that copy is older than 0.4.19, its scheduled runs cannot relay`; the second says
  `cannot relay` (0.4.9 is older than 0.4.19); the third ignores `main` as a release and uses the conditional wording;
  the fourth says that no scheduled run starts from `main` and names the copy step
