## Purpose

The repository's own CI on the hand-off commit is read job by job as the forge runs it: a GitHub job is one job of one
workflow, a re-run replaces its earlier attempt, and a commit that no job of the project ran on is never green. SPEC.md
keeps the full text of each modified requirement; the block below states what it says once this change is made.

## MODIFIED Requirements

### Requirement: L4-CI-002 Loop safety and normal CI
Checkpoint commits SHALL carry `[skip ci]`, hand-off pushes SHALL NOT, and the harness's own jobs SHALL NOT start for
harness-authored commits. When the hand-off commit has no check run on GitHub, or none but the harness's own `l4` job,
the sweeper SHALL record the repository-CI duty as `not_run` with the reason, never green (L4-GHP-008, L4-CI-012). The
other rules of L4-CI-002 stay.

#### Scenario: SCN-CI-050 (−) No check run at all on H on GitHub is not_run with the GITHUB_TOKEN reason
- **GIVEN** a GitHub repository whose hand-off commit has no check run
- **WHEN** the sweep's CI duty runs
- **THEN** it is `ci_not_run` with `pushes made with GITHUB_TOKEN start no runs`, never `ci_green`

## ADDED Requirements

### Requirement: L4-CI-010 A GitHub check run is one job of one workflow
On GitHub, `list_pipeline_jobs` SHALL key a check run of the `github-actions` app by its workflow file, its workflow
run's event and its name, and another app's by the app's slug and name, and keep the newest of a key. A re-run job's
earlier execution SHALL be dropped (`jobs?filter=latest` against `all`), and a check run that is no job of the run SHALL
stay apart. A check run whose workflow run is not found SHALL be keyed by its check suite.

#### Scenario: SCN-CI-051 (−) A failed job of one workflow is not hidden behind a passing job of the same name
- **GIVEN** on H the Actions check runs `build` of `tests.yml` (failure) and `build` of `docs.yml` (success, newer),
  and a green base
- **WHEN** the sweep's CI duty runs
- **THEN** it is `ci_failed` naming `tests.yml / build`

#### Scenario: SCN-CI-052 (+) A re-run collapses to its newest attempt
- **GIVEN** `tests.yml`'s job `test` failed in attempt 1 and passed in attempt 2 of the same workflow run, both in
  one check suite (a re-run keeps its suite)
- **WHEN** the check runs of H are listed
- **THEN** there is one job `tests.yml / test`, and it is `success`

#### Scenario: SCN-CI-053 (−) A push run and a pull_request run of one workflow are two jobs
- **GIVEN** `tests.yml` ran on H for `push` (job `build` success) and for `pull_request` (job `build` failure)
- **WHEN** the check runs of H are listed and judged
- **THEN** both are listed, and H is red

#### Scenario: SCN-CI-054 (+) A check run of another app is keyed by the app
- **GIVEN** a check run `build` of the app `codecov` (failure) and an Actions job `build` of `tests.yml` (success)
- **WHEN** the check runs of H are listed
- **THEN** there are two jobs, `codecov / build` and `tests.yml / build`, and H is red

#### Scenario: SCN-CI-055 (−) A workflow listing that cannot be read keeps every check suite apart
- **GIVEN** the check runs of SCN-CI-051 and a forge that answers 403 to the workflow-runs listing
- **WHEN** the check runs of H are listed
- **THEN** each Actions check run is keyed by its check suite, the failed `build` is still listed, and one warning says
  that the workflow runs could not be read

### Requirement: L4-CI-011 The base comparison matches the workflow and the job
`evaluate_ci`, `ci.failed` and `ci.preexisting` SHALL name a GitHub job `<workflow file> / <job>` (`<app slug> /
<name>` for another app), and a job red on H SHALL be pre-existing only when a job with that workflow file and name is
red on the base head. On GitLab a job SHALL stay its name, one per name across the pipelines of a commit, newest
pipeline first, because every pipeline of a commit runs the project's one CI configuration.

#### Scenario: SCN-CI-056 (+) The base comparison matches the workflow and the job
- **GIVEN** `tests.yml / build` red on H, and on the base head once `docs.yml / build` red and once
  `tests.yml / build` red
- **WHEN** the CI is evaluated
- **THEN** the first case is `failed` (new on H), and the second is `preexisting`

#### Scenario: SCN-CI-057 (+) GitLab keeps one job per name across the pipelines of a commit
- **GIVEN** a GitLab commit with an older pipeline whose job `test` failed and a newer one whose `test` passed
- **WHEN** its jobs are listed
- **THEN** there is one job `test`, it is `success`, and its key is `test`

### Requirement: L4-CI-012 A hand-off commit that no job of the project ran on is not_run
The repository-CI duty SHALL be `not_run`, never green, when H has no job other than the ignored `l4` job, on every
forge. Its reason SHALL say which case it is: no check run at all on GitHub (a push made with `GITHUB_TOKEN` starts
none), only the harness's own `l4` job, or no pipeline job on GitLab. The sweep and the guarded merge SHALL read H's CI
through one function, `read_handoff_ci`.

#### Scenario: SCN-CI-058 (−) A hand-off commit whose only check run is the skipped l4 job is not_run
- **GIVEN** a GitHub hand-off commit whose only check run is the harness's `l4` job, `skipped`
- **WHEN** the sweep's CI duty runs
- **THEN** it is `ci_not_run`, and the reason says that the only check run is the harness's own `l4` job and does not
  name `GITHUB_TOKEN`

#### Scenario: SCN-CI-059 (−) A GitLab commit with no job of the project is not_run
- **GIVEN** a GitLab hand-off commit with no pipeline job
- **WHEN** the sweep's CI duty runs
- **THEN** it is `ci_not_run` with `no pipeline of the project has a job on the hand-off commit`, not `ci_green`

#### Scenario: SCN-CI-060 (+) The sweep and the merge read the same verdict
- **GIVEN** five hand-off commits whose CI is running, green, failed, pre-existing, and without a job
- **WHEN** `read_handoff_ci` reads each, and the sweep's CI duty reports each
- **THEN** they agree: `running` and `ci_waiting`, `green` and `ci_green`, `failed` and `ci_failed`, `preexisting` and
  `ci_preexisting`, `not_run` and `ci_not_run`

### Requirement: L4-CI-013 A job that did not pass is not green
The newest attempt of a project job SHALL pass on success, neutral or skipped, and SHALL be red on failure, timed_out,
startup_failure or stale. A cancelled job, and a held job that a person must act on (`action_required`, a manual job
that may not fail), SHALL be `blocked`: neither green nor a fix round. A cancelled job with a finished job of the same
workflow file and name under another event SHALL count as that job. Every project job skipped SHALL be `not_run`.

#### Scenario: SCN-CI-061 (−) A cancelled, stale or action_required job is not green
- **GIVEN** a GitHub hand-off commit whose only project job concluded `cancelled`, `action_required` or `stale`
- **WHEN** the CI is read
- **THEN** the cancelled and the `action_required` job are `blocked`, the stale job is `failed`, never `green`

### Requirement: L4-CI-014 CI that may not exist yet is running
On GitHub the reader SHALL also read the workflow runs of H: a run not `completed` (not the harness's own), an
unfinished GitLab pipeline and a required check that H has not reported SHALL be running. `not_run` SHALL be final only
ten minutes after the recorded `pr.ready`, unless the repository can start no CI. An unreported required check SHALL
block the merge after the window.

#### Scenario: SCN-CI-062 (−) A queued workflow run with no check run yet is running
- **GIVEN** a GitHub hand-off commit with a queued workflow run and no check run
- **WHEN** the CI is read
- **THEN** it is `running`, not `not_run`

#### Scenario: SCN-CI-063 (−) An unfinished workflow run is running though its created jobs passed
- **GIVEN** a workflow run in progress whose only created check run passed
- **WHEN** the CI is read
- **THEN** it is `running`, and `green` once the run is completed

#### Scenario: SCN-CI-064 (−) A required check that H has not reported is running, then not_run
- **GIVEN** a base branch that requires the checks `build` and `lint`, and H with a passed `build` only
- **WHEN** the CI is read within ten minutes of the hand-off, and an hour after it
- **THEN** it is `running`, and then `unreported` naming `lint`, which blocks the merge

#### Scenario: SCN-CI-065 (−) An unfinished GitLab pipeline with no job yet is running
- **GIVEN** a GitLab hand-off commit whose pipeline is `created`, `pending` or `running` and lists no project job
- **WHEN** the CI is read
- **THEN** it is `running`, not `not_run`

### Requirement: L4-CI-015 Commit statuses are read and only the harness's own job is ignored
On GitHub the combined commit status of H SHALL be read as jobs, a failure or error red and pending running, except
the harness's own `l4/*` contexts. Only the job `l4` of the workflow `l4.yml` SHALL be ignored as the harness's own.

#### Scenario: SCN-CI-066 (−) A failed commit status makes H red
- **GIVEN** a GitHub hand-off commit with a passed check run and a commit status `ci/jenkins` in state `failure`
- **WHEN** the CI is read
- **THEN** it is `failed`, naming `status / ci/jenkins`; a pending `l4/add-x` status is ignored

#### Scenario: SCN-CI-067 (−) A failed job named l4 of another workflow is a project job
- **GIVEN** a failed job `l4` of `tests.yml`, and a failed job `l4` of `l4.yml`
- **WHEN** the CI is read
- **THEN** the first is red and the second is ignored

#### Scenario: SCN-CI-068 (−) A failed check run is not hidden behind a same-name check run of its suite
- **GIVEN** a workflow run with one job and two check runs `Test Results` of one suite, one failed and one passed
- **WHEN** the check runs of H are listed
- **THEN** the failed one is listed and H is red

#### Scenario: SCN-CI-069 (+) One CI read makes few calls
- **GIVEN** a green GitHub hand-off commit with one workflow, and a base head with 48 scheduled `l4.yml` runs
- **WHEN** the CI is read
- **THEN** it makes at most ten API calls, lists no job of an `l4.yml` run, and reads the base head only when H has a
  red job

