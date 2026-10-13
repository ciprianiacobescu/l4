## Purpose

Run the harness on a GitHub repository with GitHub-hosted runners and only the workflow's `GITHUB_TOKEN`, with
everything a GitLab run depends on. Keep the harness out of the adopting repository's history by fetching the pinned
commit at run time. Evidence: a public dummy repository, deleted after the tests.

## ADDED Requirements

### Requirement: L4-GHP-001 The workflow token knows itself
The GitHub forge SHALL use `GET /user` as its identity. When that answers 403 and `GITHUB_ACTIONS` is `true`, it SHALL
use `github-actions[bot]`, id 41898282. `own_user_id()` MUST return that identity. The sticky note MUST be matched by
its marker and by that author together, never by the marker alone.

#### Scenario: SCN-GHP-01 (+) The note appears with GITHUB_TOKEN
- **GIVEN** a job whose forge token is `GITHUB_TOKEN` and whose `GET /user` answers 403
- **WHEN** the run writes its sticky note twice
- **THEN** one comment by `github-actions[bot]` carries the marker, and the second write updated it

#### Scenario: SCN-GHP-02 (−) A person's comment with the marker is left alone
- **GIVEN** a comment by a person that contains the sticky marker
- **WHEN** the harness upserts its note
- **THEN** that comment is unchanged, and the harness's own note is created or updated

### Requirement: L4-GHP-002 A refused pull request names the setting
A 403 on creating a pull request SHALL raise the forge's auth error, with a message that names the repository setting
"Allow GitHub Actions to create and approve pull requests" and `l4 setup github`. The exit code stays 3.

#### Scenario: SCN-GHP-03 (−) The 403 is explained
- **GIVEN** a repository where Actions may not create pull requests
- **WHEN** the first push of a unit opens its draft PR
- **THEN** the run exits 3, and the message names the setting and `l4 setup github`

### Requirement: L4-GHP-003 The soft deadline on GitHub
The GitHub template SHALL set `L4_JOB_TIMEOUT_MINUTES` to the job's `timeout-minutes`. With `ci.time_budget: auto`,
`job_remaining_s` SHALL read `CI_JOB_TIMEOUT` (seconds), else `L4_JOB_TIMEOUT_MINUTES` × 60.

#### Scenario: SCN-GHP-04 (+) A long run stops before GitHub kills the job
- **GIVEN** `L4_JOB_TIMEOUT_MINUTES=180`, `soft_deadline_margin: 20m`, and 165 minutes passed since the run began
- **WHEN** the next unit would start
- **THEN** it is not started, and the run ends with exit 10

### Requirement: L4-GHP-004 Continuation by workflow_dispatch
`Forge.dispatch_continuation(ref)` SHALL return one of three answers:
- `dispatched`: the GitHub forge posted a `workflow_dispatch` of `l4.yml` on `ref`;
- `already_queued`: a run of `l4.yml` on `ref` is already queued, so nothing was posted;
- `unsupported`: GitLab and local.

A CI run that ends with exit 10 because units were left at the soft deadline, with `ci.continuation: dispatch`, SHALL
call it once for the base branch. It SHALL print `[l4] continuation: <answer> (<workflow> on <base>)` and record the
answer in `.l4-out/run.json`.

#### Scenario: SCN-GHP-05 (+) Leftover units start a new run
- **GIVEN** a GitHub run that stopped at the soft deadline with two units left and no queued `l4` run
- **WHEN** the run ends
- **THEN** one `workflow_dispatch` of `l4.yml` on the base branch is posted, and the log reads `continuation: dispatched`

#### Scenario: SCN-GHP-06 (−) No double dispatch
- **GIVEN** the same, but a run of `l4.yml` on the base branch is already queued
- **WHEN** the run ends
- **THEN** nothing is posted, and the log reads `continuation: already_queued`

### Requirement: L4-GHP-005 Other branches run the base branch's harness
For a job on any branch other than the base branch, the GitHub template SHALL check out the head of the base branch, detached, before
the first `l4` command, from the branches `actions/checkout` fetched (`fetch-depth: 0`); it runs no `git fetch`, because the
checkout keeps no credential and a private repository would refuse one. It SHALL echo `l4: base checkout <sha>` and fail
with an `::error::` when `origin/<base>` is missing.

#### Scenario: SCN-GHP-07 (−) A pushed harness change does not run
- **GIVEN** a push to `l4/openspec/x` that changes `.l4/bin/l4`
- **WHEN** the `l4` job runs
- **THEN** the log shows `l4: base checkout <base sha>`, and the shim that runs is the base branch's

### Requirement: L4-GHP-006 The skip rule exempts the base branch
The job condition SHALL skip a push whose head commit message contains `L4-Run: ` only when it is not on the base
branch. The base branch name SHALL be written as a GitHub expression string, with `'` doubled.

#### Scenario: SCN-GHP-08 (+) A trailer commit on the base still sweeps
- **GIVEN** a push to the base branch whose message has an `L4-Run: ` trailer
- **WHEN** the workflow is evaluated
- **THEN** the `l4` job runs

### Requirement: L4-GHP-007 Resume by label on GitHub
The GitHub forge SHALL implement these:
- `label_events(n)`: the `labeled` and `unlabeled` issue events, with label, actor id and time;
- `member_access(user_id)`: the collaborator role mapped to admin 50, maintain 40, write 30, triage 20, read 10, or
  None for a non-collaborator;
- `own_user_id()`: per L4-GHP-001.

#### Scenario: SCN-GHP-09 (+) A writer's label resumes a halted unit
- **GIVEN** a halted unit, and a user with write access who adds `l4:resume` to its PR
- **WHEN** the sweeper runs
- **THEN** `unit.resumed{signal}` is recorded and the unit leaves `halted`

#### Scenario: SCN-GHP-10 (−) A reader's label does nothing
- **GIVEN** the same label added by a user with read access
- **WHEN** the sweeper runs
- **THEN** the unit stays `halted`, and the note says the label was ignored

### Requirement: L4-GHP-008 No check run is not green
When the hand-off commit has no check run, the repository-CI duty SHALL be `not_run`, with a reason that names
`GITHUB_TOKEN` pushes. It MUST NOT be green.

#### Scenario: SCN-GHP-11 (−) A silent hand-off is reported
- **GIVEN** a hand-off pushed with `GITHUB_TOKEN`, and no check run on its commit
- **WHEN** the sweeper checks repository CI
- **THEN** the duty is `ci_not_run` with that reason, never green, and `l4 plan --sweep` prints it in the job log (`<unit>: ci: H <sha>: no workflow ran ...`) on every sweep, without a ledger event, as for `ci_green`

### Requirement: L4-GHP-009 Links and wording per platform
On GitHub:
- the PR body's evidence link SHALL be `<project>/blob/<ref>/<path>`;
- PRV-001's human steps SHALL say "a secret of the GitHub environment `<ci.github_environment>`";
- ENV-014 SHALL name the runner service's user, not `gitlab-runner`.

GitLab keeps its texts.

#### Scenario: SCN-GHP-12 (+) The evidence link opens on GitHub
- **GIVEN** a GitHub PR for a unit with `verification.md`
- **WHEN** its body is rendered
- **THEN** the link is `https://github.com/<o>/<r>/blob/<branch>/<path>/verification.md`

### Requirement: L4-GHP-010 The harness fetched at run time
With `harness.repository` set, `harness.commit` SHALL be required. Then:
- `l4 init --harness-repo URL [--harness-commit SHA]` SHALL write no `.l4/vendor/`.
- The shim SHALL read the repository and the commit from `.l4/config.yaml`, refuse a commit that is not 40 hex
  characters (exit 3), and run `uvx --python <pin> --from git+<repository>@<commit> l4`.
- `l4 upgrade --harness-commit SHA` SHALL rewrite only `harness.commit`, and re-render the shim, the setup script and
  the CI file.
- `buildinfo.harness_commit()` SHALL name the fetched commit.

On GitHub, with an SSH repository and the secret `L4_HARNESS_SSH_KEY` set, the template SHALL:
- write the key to `$RUNNER_TEMP` with mode 0600;
- pin GitHub's published host keys;
- export `GIT_SSH_COMMAND`.

`$RUNNER_TEMP` SHALL be hidden from every agent and gate sandbox. The tool cache key SHALL include the pinned commit.

#### Scenario: SCN-GHP-13 (+) An adopted repository holds no harness code
- **GIVEN** `l4 init --ci github --harness-repo git@github.com:o/harness.git --harness-commit <sha>`
- **WHEN** the adoption commit is made
- **THEN** it holds `.l4/config.yaml` with both pins, `.l4/bin/l4`, `.l4/bin/l4-setup` and the workflow, and no `.l4/vendor/`

#### Scenario: SCN-GHP-14 (+) A warm job fetches nothing
- **GIVEN** a tool cache saved by a job with the same pinned commit
- **WHEN** the shim runs
- **THEN** uv uses its cached tool environment, and no git fetch of the harness happens

#### Scenario: SCN-GHP-15 (−) The deploy key is not readable from a sandbox
- **GIVEN** the key at `$RUNNER_TEMP/l4-harness-key`
- **WHEN** an agent or gate in the sandbox lists `$RUNNER_TEMP`
- **THEN** the directory is empty (a tmpfs)

#### Scenario: SCN-GHP-16 (+) The ledger names the fetched commit
- **GIVEN** a harness run through the fetched shim at commit C
- **WHEN** a run starts
- **THEN** the run's first ledger event records harness commit C

### Requirement: L4-GHP-011 One command to set up GitHub
`l4 setup github [--repo owner/name] [--token-env GH_TOKEN] [--secret NAME=ENV]... [--watch] [--dry-run]` SHALL, with
a token that has admin on the repository and that it never prints, do the following idempotently, one row per step:
1. check the admin permission;
2. set the workflow permissions to write, with pull-request creation allowed;
3. create or update the environment `ci.github_environment`, with a deployment branch policy for the base branch and
   the unit prefix;
4. write each `--secret` into it, sealed with its public key;
5. set the variable `L4_SELF_PROVISION=true` when `ci.runner_tags` is empty;
6. create the labels;
7. dispatch the `l4` workflow, and follow it with `--watch`.

`--dry-run` SHALL send only reads.

#### Scenario: SCN-GHP-17 (+) A bare repository is ready in one command
- **GIVEN** an adopted repository with no environment, variable or labels
- **WHEN** `l4 setup github --secret CLAUDE_CODE_OAUTH_TOKEN=CLAUDE_CODE_OAUTH_TOKEN --watch` runs
- **THEN** every row is `CREATED` or `SET`, and the dispatched `l4` run is followed to its end

#### Scenario: SCN-GHP-18 (+) A second run changes nothing
- **GIVEN** the same repository, after SCN-GHP-17
- **WHEN** the command runs again without `--secret`
- **THEN** every row is `KEPT`

### Requirement: L4-GHP-012 Watch a GitHub run
`l4 ci watch --repo owner/name --ref REF [--tail N]` SHALL follow the newest run of `l4.yml` on the ref until it
completes. It prints each job's conclusion and the last N lines of a failed job's log, and exits 0 on success, else 1.

#### Scenario: SCN-GHP-19 (+) A failed job shows its tail
- **GIVEN** a run whose `l4` job failed
- **WHEN** `l4 ci watch` follows it
- **THEN** it prints the job's conclusion and the tail of its log, and exits 1

### Requirement: L4-GHP-013 Evidence on a public dummy repository
The change SHALL be shown live on a public dummy GitHub repository under the maintainer's account, with GitHub-hosted
runners and the workflow's `GITHUB_TOKEN`, and the harness fetched at run time. The run covers:
- a unit with an OpenCode free-model implementer and a Claude Code judge, from spec to a ready PR, with the sticky
  note and the labels;
- a continuation dispatched at a short soft deadline;
- resume by label;
- after a merge, the archive PR.

The pipeline, job and PR numbers, the note and the log lines SHALL be recorded under `docs/live/`. Afterwards the
repository SHALL be deleted and the deploy key removed from the harness repository.

#### Scenario: SCN-GHP-20 (+) The full loop runs on GitHub
- **GIVEN** the dummy repository adopted with `l4 setup github` and one OpenSpec change of one task
- **WHEN** the workflow runs
- **THEN** a ready PR with the sticky note exists, its verification passed, and after the merge an archive PR is opened, as recorded in `docs/live/`
