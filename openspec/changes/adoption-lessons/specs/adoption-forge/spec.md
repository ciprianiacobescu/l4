## Purpose

How the harness meets GitHub during an adoption: the setup of an integration base, push credentials and their failure messages, a harness pin that differs from the base's, and the repository CI jobs that the gates do not mirror.

## ADDED Requirements

### Requirement: L4-ADO-002 `l4 setup github` covers the default branch of an integration base
The default branch may differ from `forge.base_branch`. In that case `l4 setup github` SHALL:
- add the default branch to the deployment branch policies of `ci.github_environment`, or keep it;
- read `.github/workflows/l4.yml` on the default branch.

If that file is missing, a FAILED row SHALL say that schedule and dispatch need it there, and no dispatch is sent.
When the default branch is the base, nothing more is added.

#### Scenario: SCN-ADO-04 (+) An integration base gets the default branch
- **GIVEN** a repository whose default branch is `main` and a config with `forge.base_branch: staging`, and the
  workflow file on both branches
- **WHEN** `l4 setup github` runs twice
- **THEN** the first run creates the policies `staging`, `l4/*`, `l4/**/*` and `main`, and the second run keeps all
  four

#### Scenario: SCN-ADO-05 (−) The workflow is missing on the default branch
- **GIVEN** base `staging`, default branch `main`, and no `.github/workflows/l4.yml` on `main`
- **WHEN** `l4 setup github` runs
- **THEN** a FAILED row names `main` and the file, no dispatch is sent, and the exit code is 3

#### Scenario: SCN-ADO-06 (+) The base is the default branch
- **GIVEN** base `main`, which is the default branch
- **WHEN** `l4 setup github` runs
- **THEN** it creates or keeps only the policies `main`, `l4/*` and `l4/**/*`, and reads no workflow file

### Requirement: L4-ADO-003 Pushes outside CI keep the person's git credentials
Outside CI, when the variable that `forge.token_env` names is empty, every harness push SHALL run without the
harness's credential-helper settings, so the person's own git credentials apply. Nothing is written to `.git/config`.
In CI, or when the variable is set, the push SHALL use the token helper as before.

#### Scenario: SCN-ADO-07 (+) A laptop push uses the person's credentials
- **GIVEN** no CI variables and `GITHUB_TOKEN` unset, with `forge.token_env: GITHUB_TOKEN`
- **WHEN** the push settings are built
- **THEN** they hold no `credential.helper` entry, the same as the fetch settings

#### Scenario: SCN-ADO-08 (+) CI keeps the token helper
- **GIVEN** `GITHUB_ACTIONS=true` and `GITHUB_TOKEN` set
- **WHEN** the push settings are built
- **THEN** they reset the helpers and add the helper that reads `GITHUB_TOKEN`

#### Scenario: SCN-ADO-09 (+) A token set on a laptop is used
- **GIVEN** no CI variables and `GITHUB_TOKEN` set
- **WHEN** the push settings are built
- **THEN** they reset the helpers and add the helper that reads `GITHUB_TOKEN`

### Requirement: L4-ADO-004 A refused push names the forge's own token rules
The explanation of a push refused for its credential SHALL name the rules of the forge that refused it:
- **GitHub:** `contents: write` and `pull-requests: write`.
- **GitLab:** a project access token with the `write_repository` scope and the Developer role.

When the variable `forge.token_env` names is empty, the explanation SHALL say it is not set, on any forge. It never
contains a token.

#### Scenario: SCN-ADO-10 (−) GitHub wording on GitHub
- **GIVEN** a GitHub origin and a push that fails with `The requested URL returned error: 403`
- **WHEN** the failure is explained
- **THEN** the text names `contents: write`, and holds neither `Developer role` nor `write_repository`

#### Scenario: SCN-ADO-11 (−) GitLab wording on GitLab
- **GIVEN** a GitLab origin and the same failure
- **WHEN** the failure is explained
- **THEN** the text names `write_repository` and the Developer role

#### Scenario: SCN-ADO-12 (−) An unset token is named
- **GIVEN** a GitHub origin outside CI, `GITHUB_TOKEN` unset, and a push that fails with a 403
- **WHEN** the failure is explained
- **THEN** the text says `GITHUB_TOKEN is not set`

### Requirement: L4-ADO-005 A run whose harness pin differs from the base's is stopped before any work
In CI with `harness.delivery: action`, when the running harness commit differs from the pin of
`.github/workflows/l4.yml` on the checked-out base (the `uses:` sha, or the copy's `commit:` input), the run SHALL do
no work and end with exit 0 and a warning annotation (`::warning::`) that names both commits and says to update the
default branch's copy, so a scheduled run neither acts with the old harness nor turns red every schedule. Outside CI, or without a running commit, the check is
skipped.
`l4 upgrade` SHALL print the same reminder when the local `origin/HEAD` names a branch other than the base.

#### Scenario: SCN-ADO-13 (−) A scheduled run with the old pin
- **GIVEN** a base whose `l4.yml` pins commit B and a job that installed commit A (`L4_HARNESS_COMMIT=A`)
- **WHEN** `l4 doctor --ci` runs
- **THEN** the run does no work, a warning annotation names A and B and says to update `.github/workflows/l4.yml` on
  the default branch, and the job exits 0

#### Scenario: SCN-ADO-14 (+) The same pin passes
- **GIVEN** a base whose `l4.yml` pins commit A and `L4_HARNESS_COMMIT=A`
- **WHEN** `l4 doctor --ci` runs
- **THEN** the check passes

#### Scenario: SCN-ADO-15 (+) No check outside CI
- **GIVEN** a laptop with no CI variables
- **WHEN** `l4 doctor` runs
- **THEN** the check is skipped with the reason that it applies to CI jobs only

#### Scenario: SCN-ADO-16 (+) The upgrade reminds about the default branch's copy
- **GIVEN** `origin/HEAD` naming `main` and `forge.base_branch: staging`
- **WHEN** `l4 upgrade --harness-ref vX` moves the pin
- **THEN** the output says to copy `.github/workflows/l4.yml` to `main` as well

### Requirement: L4-ADO-006 `l4 doctor --adoption` names CI jobs that the gates do not mirror
`l4 doctor --adoption` SHALL warn about each job of the repository's own CI that runs on `push` or `pull_request` and
has a `run:` command that no gate command, setup command or `yolo.profiles` gate contains. The comparison ignores a
leading `uv run `, `.venv/bin/` or `python -m `. The warning lists each such job with its `services:` or `container:`.
With `forge.token_env: GITHUB_TOKEN` and `forge.merge_policy: auto`, it SHALL also say that L4's pushes start no CI.
The row never fails a run.

#### Scenario: SCN-ADO-17 (−) An unmirrored job is listed
- **GIVEN** a workflow `ci.yml` with a job `test` running `uv run pytest`, and a job `conformance` with a Postgres
  service running `uv run pytest -m postgres`, and the gate `.venv/bin/pytest --junitxml=.l4-out/junit.xml`
- **WHEN** `l4 doctor --adoption` runs
- **THEN** the warning lists `ci.yml: conformance (services: postgres)` with its command, and does not list `test`

#### Scenario: SCN-ADO-18 (−) The workflow token and automatic merges
- **GIVEN** `forge.token_env: GITHUB_TOKEN` and `forge.merge_policy: auto`
- **WHEN** `l4 doctor --adoption` runs
- **THEN** the row says that a `merge: auto` plan merges on the gates alone and names `L4_FORGE_TOKEN`,
  `forge.token_env` and `l4 upgrade`

#### Scenario: SCN-ADO-19 (+) No CI file
- **GIVEN** a repository with no workflow besides `l4.yml` and no `.gitlab-ci.yml`
- **WHEN** `l4 doctor --adoption` runs
- **THEN** the row is skipped with that reason
