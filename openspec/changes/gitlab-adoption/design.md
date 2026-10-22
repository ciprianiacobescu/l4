## Context

Read with `proposal.md`. `parse_gitlab_ci(text, load)` (`src/l4/ci/gitlab_jobs.py:217`) reads `.gitlab-ci.yml` and its
local includes into `GitlabCi` (jobs with name, source, stage, tags, trigger; `includes`; `not_checked` for what it
cannot read). Its builder keeps every job's merged keys in `raw` (`extends` resolved). Setup (`GitlabSetup` in
`src/l4/setup/gitlab.py`) reads the file on the base branch through the API and emits rows (`OK`, `WARN`, `NEW`, `SET`,
`KEPT`); doctor checks are registered in `src/l4/doctor/checks_ci.py` (`CI-001` to `CI-006`). `l4 init --ci gitlab`
edits an existing `.gitlab-ci.yml` textually (`merge_include` in `src/l4/init/ciedit.py`, comments and order kept) and
writes `_test_job` only into a file it creates.

## Decisions

### D1 The evaluator (`src/l4/ci/gitlab_rules.py`, new, pure)

```python
Source = Literal["schedule", "api", "trigger", "web", "push"]
Decision = Literal["run", "skip", "unknown"]

@dataclass(frozen=True)
class Pipeline:
    source: Source
    branch: str              # the branch the pipeline runs on (always a branch: no tag or merge-request pipelines)
    default_branch: str

def job_decision(job: Mapping[str, Any], pipeline: Pipeline) -> tuple[Decision, str]: ...   # (decision, why)
def workflow_decision(workflow: Any, pipeline: Pipeline) -> tuple[Decision, str]: ...
def jobs_on(ci: GitlabCi, pipeline: Pipeline) -> JobsOn: ...

@dataclass(frozen=True)
class JobsOn:
    workflow: Decision
    run: tuple[str, ...]
    skip: tuple[str, ...]
    unknown: tuple[str, ...]
```

- Variables known for a pipeline: `CI_PIPELINE_SOURCE` (the source), `CI_COMMIT_BRANCH` and `CI_COMMIT_REF_NAME` (the
  branch), `CI_DEFAULT_BRANCH`; `CI_COMMIT_TAG`, `CI_MERGE_REQUEST_ID` and every `CI_MERGE_REQUEST_*` are empty. Any
  other variable is unknown.
- `if:` expressions: `$V == "s"`, `$V != "s"` (also `'s'`, and `null`), `$V =~ /re/` and `$V !~ /re/` (Python `re`,
  the flags `i` honoured), a bare `$V` (non-empty), `&&`, `||`, parentheses, with GitLab precedence (`&&` before `||`).
  A comparison with an unknown variable is unknown; three-valued logic (`skip && unknown` is false, `run || unknown` is
  true, otherwise unknown). Anything the parser cannot read makes the expression unknown.
- `rules:` in order: an item whose `if` is true (or that has no `if`) decides, `when: never` is skip, any other `when`
  (default `on_success`, `manual`, `delayed`, `always`) is run; an item with `changes` or `exists` is unknown when it
  would decide; an unknown `if` before any true one makes the job unknown; no item true is skip.
- `only` / `except` (a list, or a mapping with `refs`; a mapping with `variables`, `changes` or `kubernetes` is
  unknown): the keywords `branches` (true), `tags` (false), `schedules`, `api`, `triggers`, `web`, `pushes` (true when
  the source is that one), `merge_requests`, `external`, `external_pull_requests`, `chat` (false), `pipelines` (false:
  no parent pipeline); any other string is a branch name, or a `/re/` matched against the branch. Without `only` and
  `rules` a job has `only: [branches, tags]`. A job runs when `only` matches and `except` does not.
- A job with `when: never` is skip; `when: manual` counts as run (it is a job of the pipeline). A hidden job (`.name`)
  and a trigger job are not project jobs here; the harness's own job `l4` is left out.
- `workflow: rules` (top level) is evaluated the same way; no `workflow` is run.

### D2 Setup's row (`src/l4/setup/gitlab.py`)

The row `OK .gitlab-ci.yml on <base>` reads, instead of `(they run on every scheduled pipeline too)`:
`includes .l4/ci/l4.gitlab-ci.yml; the project's own jobs on a scheduled pipeline of <base>: run: <names or none>; skip:
<names or none>[; unknown: <names>]` (names comma-separated, at most 8 then `(+k more)`).

### D3 The empty-pipeline warnings (setup and `CI-007`; L4-INS-008)

Only a project job in a normal stage counts: a job whose stage is `.pre` or `.post` that runs does not make the
pipeline acceptable to GitLab. `JobsOn` therefore also carries `normal_run: tuple[str, ...]` and `normal_unknown`
(the run and unknown jobs whose stage is not `.pre`/`.post`; a job without `stage` is in `test`).
The pipelines checked are `schedule` and `api` on the base branch (`Pipeline(source, base, default_branch)`) and
`push` on a unit branch (`Pipeline("push", "<forge.branch_prefix>unit", default_branch)`: a person's answer pushed to a
unit branch starts the harness), each in turn:
- `workflow == "skip"`: `WARN workflow:rules` (setup) and doctor `CI-007` warn with
  `.gitlab-ci.yml's workflow:rules create no <source> pipeline on <branch>: the l4 job never runs on one`.
- else, `normal_run` and `normal_unknown` both empty: `WARN pipeline` and `CI-007` warn with
  `on a <source> pipeline of <branch> only the l4 job (stage .post) would be created, and GitLab refuses a pipeline
  whose jobs are all in .pre or .post ("pipeline would have been empty"): add a job in a normal stage that runs on
  schedule, api, trigger and web pipelines and on pushes to <forge.branch_prefix> branches (l4 init --ci gitlab adds
  l4-pipeline-anchor)`, where `<branch>` is the base for schedule and api and `<forge.branch_prefix>*` for push.
`CI-007` ("The harness's pipelines are not empty", `warn`, `CONFIG_SCOPES`) reads the local `.gitlab-ci.yml` and its
local includes; it is `skip` when `ci.platform` is not `gitlab` or the file is missing, `pass` with
`a project job in a normal stage runs on the harness's pipelines` otherwise. The base is `forge.base_branch`, else the
default branch the doctor knows, else `main`.

### D4 The anchor job of `l4 init` (`src/l4/init/ciedit.py`, `init.py`; L4-INS-009)

When `l4 init --ci gitlab` edits an existing `.gitlab-ci.yml` (it adds the include) and, after the edit, D3 finds an
empty pipeline (no `workflow` skip; `normal_run` and `normal_unknown` empty for one of the checked pipelines), and no
job named `l4-pipeline-anchor` exists, init appends to the file:

```yaml

# Added by `l4 init`: GitLab refuses a pipeline whose jobs are all in .pre or .post, and the l4 job is in .post. This
# job gives the harness's own pipelines (schedule, api, trigger, web) a job in a normal stage; it only echoes.
l4-pipeline-anchor:
  stage: <stage>
  tags: [<tag>, ...]
  script:
    - echo "L4 pipeline ($CI_PIPELINE_SOURCE on $CI_COMMIT_REF_NAME)"
  rules:
    - if: '$CI_PIPELINE_SOURCE =~ /^(schedule|api|trigger|web)$/'
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH =~ /^<prefix>/'
```

`<prefix>` is `forge.branch_prefix` with every regex metacharacter and `/` escaped (`l4/` gives `l4\/`). `<stage>` is `test` when the file has no top-level `stages:` or its list holds `test`, else its first stage that is not
`.pre` or `.post`; the `tags:` line is left out when `ci.runner_tags` is empty. The text keeps the file's line endings.
The edit must still parse back (`_parses_back`); the init report gains the line
`added the job l4-pipeline-anchor: GitLab refuses a pipeline with only .pre/.post jobs`. A file init creates is
unchanged (it already has a test job).

### D5 The bot's level (`src/l4/setup/gitlab.py`; L4-INS-010)

- `SetupOptions` gains `merge_policy: str = "human"` (from `forge.merge_policy` of the config, as `base_branch` is).
- `needed_level()`: `40` (Maintainer) when `merge_policy == "auto"` and the base branch's protection (the entry of
  `GET projects/:id/protected_branches` whose `name` equals the base or matches it as a wildcard, `fnmatch`) has
  `merge_access_levels` with no entry below 40 that is not 0, and at least one entry of 40 or more; else `30`. An
  unprotected base, a Developer entry or `merge_policy: human` is `30`. A protection whose only merge entries are 0
  (No one) gives `30` and the row `WARN protected branch <base>` `accepts merges from no one: no unit can be merged;
  allow Maintainers (or Developers) to merge, or set forge.merge_policy: human`.
- A new token (first setup or `--rotate`) is created with `access_level: needed_level()`. When that is 40, the next row
  is `INFO token l4-bot` `a Maintainer token: forge.merge_policy is auto and <base> accepts merges from Maintainers
  only (a Maintainer may also push to every branch protected for Maintainers)`.
- A kept active token whose `access_level` is below `needed_level()`: `WARN token l4-bot id=<id>` `level <n> cannot
  merge into <base>, which accepts merges from Maintainers only, and forge.merge_policy is auto: run l4 setup gitlab
  --rotate --revoke-old to create a Maintainer token (GitLab does not change a bot's role), or set
  forge.merge_policy: human`.
- `--dry-run` prints the level it would create.

## Contracts (texts, exact)

The texts in D2, D3, D4 and D5 are exact; `<base>`, `<source>`, `<stage>`, `<id>`, `<n>` filled in.

## Risks / Trade-offs

- The evaluator reads a subset of GitLab's rules language. Mitigation: anything else is `unknown`, and an unknown job
  never raises the empty-pipeline warning or makes init add a job.
- A Maintainer token can do more than merge. Mitigation: only when the config asks for automatic merges into a branch
  that accepts Maintainer merges only; the row says so; the token is masked and scoped to the `l4` environment, and the
  agents never see it (the sandbox clears the environment).
