## Purpose

On GitLab, the harness knows which of the project's jobs run on the pipelines it starts, names a pipeline GitLab
would refuse as empty before it happens, adds the job that prevents it when it edits an existing CI file, and creates a
bot token that can merge when the configuration asks for automatic merges.

## ADDED Requirements

### Requirement: L4-INS-007 Setup reads which project jobs run on a scheduled pipeline
`l4 setup gitlab` SHALL decide, for each of the project's own jobs, whether it runs on a scheduled pipeline of the base
branch, from its `rules`, `only`, `except` and `when` and from `workflow: rules`, as run, skip or unknown (an expression
or key it cannot evaluate is unknown), and SHALL report `the project's own jobs on a scheduled pipeline of <base>: run:
…; skip: …` (and `unknown: …` when there are any) instead of saying they all run.

#### Scenario: SCN-INS-18 (+) Jobs excluded from schedules are reported as skipped
- **GIVEN** a `.gitlab-ci.yml` whose jobs `all_tests` and `staging` have `except: [schedules, api, triggers]`, a job
  `lint` with `rules: [{if: '$CI_PIPELINE_SOURCE == "push"'}]`, and a job `report` with `only: [schedules]`
- **WHEN** setup reads it for base `master`
- **THEN** the row says `run: report; skip: all_tests, lint, staging`

#### Scenario: SCN-INS-19 (+) What the evaluator cannot read is unknown
- **GIVEN** a job with `rules: [{if: '$DEPLOY_ENV == "prod"'}]` and a job with `only: {variables: [...]}`
- **WHEN** setup reads it
- **THEN** both are listed under `unknown`

### Requirement: L4-INS-008 A pipeline GitLab would refuse as empty is named
`l4 setup gitlab` and doctor check `CI-007` SHALL warn when, on a schedule or an api pipeline of the base branch, no
project job runs and none is unknown (only the `.post` job `l4` would be created, which GitLab refuses), naming the fix,
and when `workflow: rules` create no such pipeline at all.

#### Scenario: SCN-INS-20 (−) Only the l4 job would run on a schedule
- **GIVEN** the file of SCN-INS-18 without the job `report`
- **WHEN** setup runs and `l4 doctor` runs
- **THEN** setup prints `WARN pipeline` and `CI-007` warns, both with `on a schedule pipeline of master only the l4 job
  (stage .post) would be created, and GitLab refuses a pipeline whose jobs are all in .pre or .post`; the same for `api`

#### Scenario: SCN-INS-21 (+) An anchor job or an unknown job is enough
- **GIVEN** the file of SCN-INS-20 with `l4-pipeline-anchor` added, and in turn with a job whose rule is unknown
- **WHEN** `l4 doctor` runs
- **THEN** `CI-007` does not warn

#### Scenario: SCN-INS-22 (−) workflow:rules exclude schedules
- **GIVEN** `workflow: {rules: [{if: '$CI_PIPELINE_SOURCE == "schedule"', when: never}, {when: always}]}`
- **WHEN** `l4 doctor` runs
- **THEN** `CI-007` warns with `.gitlab-ci.yml's workflow:rules create no schedule pipeline on <base>: the l4 job never
  runs on one`

### Requirement: L4-INS-009 l4 init adds the anchor job when it edits a CI file whose jobs skip the harness's pipelines
When `l4 init --ci gitlab` edits an existing `.gitlab-ci.yml` and, after the edit, no project job runs and none is
unknown on a schedule or an api pipeline of the base branch, init SHALL append the job `l4-pipeline-anchor` (a normal
stage, the runner tags, a script that only echoes, rules for schedule, api, trigger and web pipelines) with a comment
that says why, unless a job of that name exists, and SHALL say so in its report. A file it creates and a file whose jobs
run on those pipelines MUST stay as today.

#### Scenario: SCN-INS-23 (+) init appends the anchor job
- **GIVEN** the file of SCN-INS-20 with `stages: [build, test, deploy]` and `ci.runner_tags: [agentic]`
- **WHEN** `l4 init --ci gitlab` adds the include
- **THEN** the file ends with the comment and `l4-pipeline-anchor` in stage `test` with `tags: [agentic]`, the file
  parses back, the report says `added the job l4-pipeline-anchor`, and `CI-007` passes

#### Scenario: SCN-INS-24 (+) init leaves a file alone when a job runs on schedules
- **GIVEN** a `.gitlab-ci.yml` whose job `test` has no `rules`, `only` or `except`
- **WHEN** `l4 init --ci gitlab` adds the include
- **THEN** no job is appended

#### Scenario: SCN-INS-25 (+) The stage follows the file's stages
- **GIVEN** the file of SCN-INS-23 with `stages: [.pre, checks, ship]`
- **WHEN** init appends the job
- **THEN** its stage is `checks`

### Requirement: L4-INS-010 The bot token can merge when the configuration asks for automatic merges
`l4 setup gitlab` SHALL create the `l4-bot` token as a Maintainer when `forge.merge_policy` is `auto` and the base
branch's protection accepts merges from Maintainers only, and say why, and as a Developer otherwise. It SHALL warn,
naming `l4 setup gitlab --rotate --revoke-old` and `forge.merge_policy: human`, when it keeps an active token whose
level cannot merge into such a branch, and when the base branch accepts merges from no one.

#### Scenario: SCN-INS-26 (+) A Maintainer token for automatic merges into a Maintainer-only branch
- **GIVEN** `forge.merge_policy: auto`, base `master` protected with merges allowed to Maintainers only, and no token
- **WHEN** setup runs
- **THEN** the token is created with `access_level: 40`, and the row `INFO token l4-bot` says `a Maintainer token:
  forge.merge_policy is auto and master accepts merges from Maintainers only`

#### Scenario: SCN-INS-27 (−) A kept Developer token is named
- **GIVEN** the config of SCN-INS-26 and an active level-30 `l4-bot` token with its variable set
- **WHEN** setup runs without `--rotate`
- **THEN** it keeps the token and prints `WARN token l4-bot id=<id>` with `level 30 cannot merge into master` and
  `--rotate --revoke-old`

#### Scenario: SCN-INS-28 (+) Developer stays the level otherwise
- **GIVEN** `forge.merge_policy: human`, and in turn `auto` with a base that Developers may merge into, and in turn an
  unprotected base
- **WHEN** setup creates the token
- **THEN** its level is 30 and no `INFO token` row is printed
