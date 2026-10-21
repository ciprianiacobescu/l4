## Purpose
Generated CI integration for GitLab CI (17.5.2 CE reference) and GitHub Actions at parity: pipeline shape, exit-code plumbing, loop safety, push credentials, untrusted-event handling, counted continuations and the scheduled sweeper.

## ADDED Requirements

### Requirement: L4-CI-001 (part a) Pipeline order and fail-fast doctor
Every pipeline MUST run, in order, `l4 doctor --ci`, then `l4 plan --json`, then one `l4 run --unit <id>` job per actionable unit, then outcome rendering; a failing doctor MUST stop the pipeline before any probe, agent or LLM call.

#### Scenario: SCN-CI-09 (−) Insufficient token scope blocks before spending
- **GIVEN** a GitLab token without `api` scope
- **WHEN** the pipeline starts
- **THEN** `doctor --ci` fails (exit 3) before any agent or probe call

### Requirement: L4-CI-001 (part b) Triggers
The rendered CI MUST be triggered by: a push to the base branch touching spec roots; a push to `<branch_prefix>**` by a non-harness actor; a schedule (sweeper `l4 plan --sweep`, every 30 minutes by default); and a manual dispatch with inputs `unit`, `mode` (`run|verify|plan|doctor`) and `dry_run`.

#### Scenario: SCN-CI-19 (+) Rendered triggers match the contract
- **GIVEN** a default config with `forge.branch_prefix: "l4/"`
- **WHEN** `l4 ci render --platform github` and `l4 ci render --platform gitlab` run
- **THEN** both outputs contain the four trigger kinds, the GitHub `workflow_dispatch` inputs are exactly `unit`, `mode` and `dry_run`, and the GitLab jobs have no `rules: changes`

### Requirement: L4-CI-001 (part c) Exit codes pass through map-exit
Every CI step that can return a semantic exit code MUST be written as `l4 <command> || l4 ci map-exit $?`; on GitHub `l4 ci map-exit` MUST print a `::warning::` or `::notice::` annotation and exit 0 for codes 10, 11 and 12 and 1 for every other non-zero code; on GitLab it MUST print an annotation and re-exit with the original code.

#### Scenario: SCN-CI-16 (+) `set -e` safe exit plumbing
- **GIVEN** a CI shell with `set -e` and `l4 run` exiting 11
- **WHEN** the step `l4 run --unit X || l4 ci map-exit $?` runs
- **THEN** GitHub: the step succeeds with a warning annotation; GitLab: the job ends with exit 11 and is shown as an allowed failure

#### Scenario: SCN-CI-10 (+) Exit-code rendering on GitHub
- **GIVEN** a run exiting 11
- **WHEN** the step completes
- **THEN** the job succeeds with a `::warning::` annotation naming the open questions

#### Scenario: SCN-CI-21 (−) Failure codes are never downgraded
- **GIVEN** a run exiting 13 and a run exiting 1
- **WHEN** `l4 ci map-exit 13` and `l4 ci map-exit 1` run with the GitHub platform
- **THEN** both exit 1 and print an error annotation, never a notice or warning

### Requirement: L4-CI-001 (part d) GitHub Actions workflow shape
The generated `l4.yml` MUST contain a job `doctor`, a job `plan` that outputs the actionable unit list as JSON, and a job `run` with `strategy.matrix.unit: ${{ fromJSON(needs.plan.outputs.units) }}`, `max-parallel: ci.max_parallel_units`, skipped when the list is empty, `concurrency: {group: l4-${{ matrix.unit }}, cancel-in-progress: false}`, `actions/checkout` with `persist-credentials: false` and `timeout-minutes` <= 345.

#### Scenario: SCN-CI-01 (+) GitHub end to end
- **GIVEN** a spec merged to `main`
- **WHEN** the push event runs `l4.yml`
- **THEN** `doctor` → `plan` → one matrix job per unit with `concurrency: l4-<unit>`; draft PR created

#### Scenario: SCN-CI-22 (−) A workflow that can cancel or persist credentials is rejected
- **GIVEN** a rendered `l4.yml` edited to `cancel-in-progress: true` and `persist-credentials: true`
- **WHEN** `l4 doctor --ci` runs
- **THEN** CI-003 fails for the cancelling concurrency group and CI-001 fails for the drifted file, exit 3

### Requirement: L4-CI-001 (part e) GitLab detect job
The GitLab template MUST define a `detect` job that runs on pipeline sources `push|web|api|trigger|schedule` (never `rules: changes`, which is always true on new branches) with the single script line `l4 doctor --ci && l4 plan --json $L4_PLAN_FLAGS > plan.json && l4 ci render-child --plan plan.json > child.yml`, where `L4_PLAN_FLAGS` is empty except `--sweep` on scheduled pipelines; an empty plan MUST render a child pipeline with a single no-op job.

#### Scenario: SCN-CI-11 (+) GitLab detect job works when there is work
- **GIVEN** two actionable units
- **WHEN** the `detect` job runs `l4 doctor --ci && l4 plan --json > plan.json && l4 ci render-child --plan plan.json > child.yml`
- **THEN** every command exits 0, `child.yml` has two jobs, each with `resource_group` and `tags: [agentic]`

#### Scenario: SCN-CI-23 (+) Empty plan renders a no-op child
- **GIVEN** a plan with zero actionable units
- **WHEN** `l4 ci render-child --plan plan.json` runs
- **THEN** exit 0 and `child.yml` contains exactly one job whose script is a no-op and which carries the runner tags

### Requirement: L4-CI-001 (part f) GitLab child pipeline jobs
The detect job MUST launch the child pipeline via `trigger: {include: [{artifact: child.yml, job: detect}], strategy: depend}`, and each child job MUST run `l4 run --unit <id> || l4 ci map-exit $?` with `resource_group: l4-<id>` (characters GitLab rejects replaced), `interruptible: false`, `tags` taken from `ci.runner_tags` and `allow_failure: {exit_codes: [10, 11, 12]}`.

#### Scenario: SCN-CI-02 (+) GitLab 17.5 CE end to end on a tagged shell runner
- **GIVEN** the reference project with runner tags `[agentic]`
- **WHEN** a push pipeline runs
- **THEN** `detect` creates a child pipeline; each unit job has `resource_group: l4-<unit>` and `tags: [agentic]`; an MR is created via the project access token

#### Scenario: SCN-CI-24 (−) A unit id GitLab would reject as a resource group name
- **GIVEN** a unit `kiro:user auth/v2`
- **WHEN** `l4 ci render-child` renders its job
- **THEN** the `resource_group` value contains only letters, digits, `-`, `_` and `.`, two distinct units never share a value, and the YAML parses back to the same script line

### Requirement: L4-CI-001 (part g) Runner tags and serialisation are checked
Doctor check CI-002 MUST fail (exit 3) when a rendered GitLab job lacks `ci.runner_tags` while the project's runner has `run_untagged: false`, and CI-003 MUST fail when serialisation (GitHub `concurrency`, GitLab `resource_group`) is absent from a job that runs `l4 run`.

#### Scenario: SCN-CI-06 (−) Missing runner tag is caught before it hangs
- **GIVEN** a GitLab runner with `run_untagged: false` and a rendered job without tags
- **WHEN** `l4 doctor --ci`
- **THEN** CI-002 error, exit 3

#### Scenario: SCN-CI-14 (+) Live check of the reference runner tags
- **GIVEN** the reference project `example-group/dummy-agentic` and the rendered l4 jobs
- **WHEN** a live pipeline runs
- **THEN** the l4 jobs run on runner #12 `l4-runner` (job API `runner.id == 12`), unlike the untagged template jobs of pipeline #2521, which ran on runner #8

### Requirement: L4-CI-001 (part h) Shell-executor homes and job timeout
On a shell executor the harness MUST create per-job homes for Serena under `$CI_BUILDS_DIR/.l4-home/<job id>` and leave agent CLIs on their default homes, and doctor CI-004 MUST warn when the project job timeout is shorter than the time budget the harness assumes.

#### Scenario: SCN-CI-25 (−) Short job timeout is flagged
- **GIVEN** a GitLab project whose `build_timeout` is 3600 seconds and `ci.time_budget: 3h`
- **WHEN** `l4 doctor --ci` runs
- **THEN** CI-004 reports a warning recommending a longer timeout, the exit code stays 0, and the job home path is `$CI_BUILDS_DIR/.l4-home/<job id>`

### Requirement: L4-CI-001 (part i) GitLab template forms
The GitLab template MUST be shipped as an `include:` template (`l4.gitlab-ci.yml`) that uses only features of GitLab 17.5 CE, and MUST be additionally shipped as a CI/CD component only when doctor FORGE-004 confirms that the server supports components.

#### Scenario: SCN-CI-26 (−) Server without component support still works
- **GIVEN** a GitLab server where FORGE-004 reports no component support
- **WHEN** `l4 init --ci gitlab` runs
- **THEN** only the include-template form is written and the rendered YAML passes the project's CI Lint API

### Requirement: L4-CI-002 (part a) Checkpoint commits start no pipelines
Every checkpoint commit (task commits, WIP snapshots, ledger updates, lock commits) MUST carry `[skip ci]` in its message so push and merge-request/pull-request pipelines skip it; GitHub checkpoints are pushed with `GITHUB_TOKEN` and GitLab checkpoints are additionally pushed with `-o ci.skip`.

#### Scenario: SCN-CI-03 (−) Checkpoint commits start no pipelines
- **GIVEN** a project with push **and** merge-request pipelines (GitLab) or push **and** pull_request workflows (GitHub)
- **WHEN** the harness pushes checkpoint commits
- **THEN** every checkpoint commit message contains `[skip ci]`; no pipeline/workflow run executes for them (GitHub may list none or skipped runs, never runs awaiting approval)

### Requirement: L4-CI-002 (part b) Hand-off pushes run the repository CI
Hand-off pushes (the hand-off commit H and the archive commit) MUST NOT carry `[skip ci]` and MUST NOT use `-o ci.skip`, so the repository's own CI runs on the head a human merges; on GitLab they are normal pushes with the project access token.

#### Scenario: SCN-CI-13 (+) The repository's own CI runs on hand-off commits only
- **GIVEN** a GitLab project with its own `test` job and the l4 include
- **WHEN** the harness pushes checkpoints and then the hand-off commit
- **THEN** checkpoints create no pipelines; the hand-off commit creates a pipeline in which the repo's `test` job runs and the l4 jobs are skipped by the `L4-Run` trailer rule

### Requirement: L4-CI-002 (part c) GitHub App token minted at hand-off
For a GitHub hand-off push the harness MUST mint a fresh App installation token from `forge.github_app` immediately before the push, MUST keep the App private key out of every agent and gate sandbox, and MUST NOT write the token to logs.

#### Scenario: SCN-CI-15 (+) The App token is minted at hand-off time
- **GIVEN** a GitHub run whose hand-off happens 3 hours after the job started
- **WHEN** the hand-off push is made
- **THEN** the harness mints a fresh installation token from `forge.github_app` immediately before the push; the push triggers the repository's workflows; the token never appears in logs or in a sandbox

### Requirement: L4-CI-002 (part d) Harness jobs skip harness-authored commits
The harness's own jobs MUST NOT start for harness-authored commits: the GitHub router `if:` and the GitLab rule `if: '$CI_COMMIT_MESSAGE =~ /\nL4-Run: /'` with `when: never` MUST be present on every l4 job, while the repository's other jobs still run.

#### Scenario: SCN-CI-04 (−) Bot commit that does trigger is ignored
- **GIVEN** a pipeline started by a push whose head commit has an `L4-Run` trailer
- **WHEN** the router runs
- **THEN** it plans nothing for that unit and exits 0

### Requirement: L4-CI-002 (part e) Iteration counted from the ledger
The iteration number MUST be counted from the ledger and never taken from dispatch inputs or CI variables, and above `budgets.max_iterations_per_unit` the run MUST refuse with exit 13 before any agent call.

#### Scenario: SCN-CI-12 (−) A manual dispatch cannot reset the iteration budget
- **GIVEN** a unit at ledger iteration 10 (`max_iterations_per_unit: 10`)
- **WHEN** a human dispatches the run workflow manually
- **THEN** the run reads iteration 10 from the ledger and refuses (exit 13); no agent call

### Requirement: L4-CI-002 (part f) GitLab push credentials stay out of git config
GitLab pushes MUST authenticate with the project access token from the environment variable named by `forge.token_env` through a per-command git credential helper, never in a remote URL, and at job start the harness MUST replace the credential-bearing `origin` URL the runner wrote with the same URL without credentials.

#### Scenario: SCN-CI-27 (−) Token never lands in git config or logs
- **GIVEN** a shell-runner checkout whose `origin` URL contains `gitlab-ci-token:<secret>@`
- **WHEN** `l4 doctor --ci` and a push run
- **THEN** `git config --get remote.origin.url` has no credentials afterwards, no file under `.git/` and no log line contains the token value, and the push succeeds through the credential helper

### Requirement: L4-CI-003 Untrusted events never run the harness
Untrusted events (fork pull requests, comments by non-members) MUST NOT run the harness: the generated GitHub workflow and GitLab rules MUST exclude fork pull-request and fork merge-request events from every l4 job.

#### Scenario: SCN-CI-05 (−) Fork PRs never run the harness
- **GIVEN** a pull request from a fork
- **WHEN** workflows evaluate
- **THEN** no harness job runs

### Requirement: L4-CI-004 (part a) Exactly one continuation per exit 10
A run that exits 10 MUST have dispatched exactly one continuation for its unit before exiting, made idempotent by the ledger iteration and the `L4-Iteration` commit trailer, so a retried job never dispatches a second one.

#### Scenario: SCN-CI-07 (+) Exactly one continuation per exit 10
- **GIVEN** a run exiting 10 whose job is retried by CI
- **WHEN** both attempts finish
- **THEN** one continuation exists for `iteration+1` (idempotency on `L4-Iteration` + ledger)

### Requirement: L4-CI-004 (part b) Failed dispatch is recorded
When a continuation dispatch fails, the run MUST checkpoint its work, record `continuation: failed` in `outcome.json` and the ledger, exit 10, and leave the unit to the sweeper.

#### Scenario: SCN-CI-08 (−) Continuation dispatch fails
- **GIVEN** an invalid trigger token
- **WHEN** the run needs a continuation
- **THEN** work is checkpointed, `outcome.json.continuation = "failed"`, exit 10; the sweeper resumes the unit later

### Requirement: L4-CI-004 (part c) Platform dispatch calls
On GitLab a continuation MUST be `POST /projects/:id/trigger/pipeline` with the trigger token from `L4_TRIGGER_TOKEN` and `variables[L4_UNIT]` only; on GitHub it MUST be a `workflow_dispatch` of `l4.yml` with the `unit` input only; the iteration is never passed.

#### Scenario: SCN-CI-28 (+) GitLab continuation request shape
- **GIVEN** a run exiting 10 for unit `openspec:add-login` on GitLab
- **WHEN** the continuation is dispatched
- **THEN** exactly one trigger request is recorded with `ref` = the base branch, `variables[L4_UNIT]=openspec:add-login`, no iteration variable, and `continuation: dispatched` in `outcome.json`

### Requirement: L4-CI-004 (part d) Sweeper resumes waiting and expired units
The scheduled sweeper (`l4 plan --sweep`) MUST resume `waiting_capacity` units whose `retry_after` has passed and units whose lease expired mid-step, and MUST leave units whose `retry_after` is in the future untouched.

#### Scenario: SCN-CI-29 (+) Sweeper resumes after the reset
- **GIVEN** a unit in `waiting_capacity` with `retry_after` in the past and another with `retry_after` in the future
- **WHEN** `l4 plan --sweep` runs
- **THEN** exactly one continuation is dispatched, for the first unit; the second is reported with its `retry_after`

### Requirement: L4-CI-004 (part e) Sweeper reacts to PR state
The sweeper MUST detect merged and closed PRs and hand them to the archive handlers (L4-ARC-003, L4-ARC-005), and MUST refresh `in_review` units whose base moved as specified by L4-ARC-006.

#### Scenario: SCN-CI-30 (+) Sweeper hands merged and closed PRs to the archive handlers
- **GIVEN** the fake forge holds one merged and one closed-unmerged unit PR
- **WHEN** `l4 plan --sweep` runs
- **THEN** the merged unit becomes `merged` and the closed one `abandoned`, each with one ledger event, and a second sweep changes nothing

### Requirement: L4-CI-004 (part f) Sweeper label and intake duties
The sweeper MUST honour the `l4:resume` label only when set by a member with at least Developer/Write access, removing it otherwise with a comment, and MUST re-run intake for `rejected` units whose inputs changed.

#### Scenario: SCN-CI-31 (−) A non-member's resume label is ignored
- **GIVEN** `l4:resume` set on a halted unit's PR by a user without Developer/Write access
- **WHEN** `l4 plan --sweep` runs
- **THEN** the unit stays `halted`, the label is removed and an explanatory comment is posted

### Requirement: L4-CI-004 (part g) Sweeper repairs mirrors
The sweeper MUST repair the forge mirrors (labels, commit status, PR body) from `state.json` whenever they differ, and MUST make no forge write when they already match.

#### Scenario: SCN-CI-32 (+) Mirrors are repaired from state
- **GIVEN** a unit in `in_review` whose PR carries the label `l4:verifying` and a pending status
- **WHEN** `l4 plan --sweep` runs
- **THEN** the label becomes `l4:in_review`, the status `success`, the body is regenerated, and a second sweep issues zero write calls
