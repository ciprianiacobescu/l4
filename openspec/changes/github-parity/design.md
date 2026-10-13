## Context

[V, code] marks the parity survey of 2026-10-11 on `spike/hosted-agent-setup` at 103fd8c. Evidence for the hosted runner
itself is `docs/spikes/06-hosted-runner-setup.md` §7, run 38164195347.

- **Forge** (`src/l4/forge/github.py`).
  - Has: PRs (find, get, list, create), draft↔ready through GraphQL, labels, the sticky note, `list_pipeline_jobs` from
    check runs, `job_log`, and `x-access-token` git credentials.
  - Stubs: `label_events` → `[]`, `member_access` → None, `own_user_id` → None (`:365-373`).
  - The sticky note looks up its author with `GET /user` (`:397`).
- **CI template** (`l4.github.yml`, rendered by `ci/github.py`).
  - One routed job.
  - No base checkout for a unit-branch push.
  - The `L4-Run:` skip applies to every branch.
  - `workflow_dispatch:` is a trigger, and the job has `actions: write`.
  - No job-timeout variable is passed.
- **Orchestrator.** `job_remaining_s` reads `ci.time_budget` or GitLab's `CI_JOB_TIMEOUT` (`orchestrator.py:1141`).
  `run_units` returns exit 10 when units are left (`:1178-1196`). Nothing dispatches a continuation on either forge.
- **Sweeper.** No check run at the hand-off commit is recorded as green (`sweeper.py:546-549`).
- **Resume.** `resume_label` allows a resume from GitLab access level 30 (Developer) up (`ci/resume_label.py:15,62`).
- **Harness delivery.**
  - The shim runs only the vendored copy (`ci/render.py`, `_SHIM`).
  - `harness.version` and `harness.commit` exist in the config (`schema.py:82`).
  - L4-INS-001 and L4-INS-005 specify `uvx --from git+<url>@<sha>`, which was never built (forge-and-ci 1.14; SPEC Q1
    decided "local only" until a hosting choice). The harness now lives in a private GitHub repository.
- **GitHub facts.**
  - [V] `GET /users/github-actions[bot]` → `{login: github-actions[bot], id: 41898282, type: Bot}`.
  - [D] "events triggered by the GITHUB_TOKEN will not create a new workflow run, with the following exceptions:
    workflow_dispatch and repository_dispatch events always create workflow runs" (docs.github.com, Triggering a
    workflow).
  - [V] Environments with deployment branch policies and environment secrets work on a private Free-plan repository
    (spike 06 finding 11).

## Goals

- `l4 run` completes on a GitHub repository with GitHub-hosted runners and only the workflow's `GITHUB_TOKEN` as the
  forge token: draft PR, notes, labels, verification, hand-off, then archive after a person merges.
- GitHub gets everything GitLab has that a run depends on: deadline, base-branch harness, skip rule, resume by label,
  setup in one command, watch.
- An adopting repository's history holds no harness code. The harness is fetched at the pinned commit and cached on
  the runner.

## Non-Goals

- GitHub App installation tokens (forge-and-ci 2.11). With `GITHUB_TOKEN`, the hand-off push starts no repository CI.
  This change reports that honestly (D8) instead of solving it.
- Commit statuses, approvals and `merge_policy`, which are missing on both forges.
- Continuation on GitLab (forge-and-ci 2.6). Its forge answers `unsupported`.
- Hiding a public repository's Actions logs. Public logs and artifacts are public. The dummy repository is deleted after
  the tests.

## Decisions

### D1. `GITHUB_TOKEN` knows who it is

The forge's identity is `GET /user`. When that answers 403 and `GITHUB_ACTIONS=true`, the identity is
`github-actions[bot]`, id 41898282 [V]. `own_user_id()` returns it. The sticky note is found by the marker AND that
author, so a person's comment that quotes the marker is never overwritten.

Rejected: matching the marker alone. Anyone who can comment could then hijack the note.

### D2. A refused pull request says why

A 403 on `create_pr` raises `ForgeAuthError` with this hint: "GitHub refused to create the pull request (403). Allow
GitHub Actions to create pull requests (Settings > Actions > General > Workflow permissions), or run `l4 setup
github`". The exit code stays 3, because a run that cannot hand off must not look fine. The doctor gets no new row:
`l4 setup github` sets the permission, and the hint names it.

### D3. The soft deadline on GitHub

The template renders `L4_JOB_TIMEOUT_MINUTES: "<n>"` from the same constant as `timeout-minutes`. `job_remaining_s`
with `time_budget: auto` reads, in order:
1. `CI_JOB_TIMEOUT` (seconds, GitLab);
2. `L4_JOB_TIMEOUT_MINUTES` × 60.

GitHub exposes no job start time, so the start is the run's own start. The minutes spent on checkout, cache and
setup fall inside `soft_deadline_margin` (20 m).

### D4. Continuation by `workflow_dispatch`

`Forge.dispatch_continuation(ref: str) -> Literal["dispatched", "already_queued", "unsupported"]`:
- **GitHub**: `GET /repos/{o}/{r}/actions/workflows/l4.yml/runs?branch=<ref>&status=queued`. When a queued run exists,
  `already_queued`. Else `POST …/workflows/l4.yml/dispatches {"ref": <ref>}` → `dispatched`.
- **GitLab and local**: `unsupported`.

`run_all` calls it once per run, only when every one of these holds:
- the run ended with exit 10 because units were left at the soft deadline;
- `ci.continuation` is `dispatch`;
- the run is in CI.

It prints `[l4] continuation: <answer> (<workflow> on <base>)` and writes the answer into `.l4-out/run.json`. The
`l4` job needs `actions: write`, which the template has. A dispatched run plans afresh and finds the left units.

### D5. Other branches run the base branch's harness

The GitHub template gets a step after checkout. When `github.ref_name` is not the base branch, it runs
`git checkout --detach origin/<base>` (the ref `actions/checkout` with `fetch-depth: 0` already fetched; no `git fetch`, which a
private repository refuses without a credential; an `::error::` when the ref is missing), and echoes
`l4: base checkout <sha>`. This is the GitLab rule (`l4.gitlab-ci.yml:39`).

Without it, a push to `l4/**` by anyone with write access could change the shim, `.l4/vendor/` or `harness.commit`,
and run code of their choosing with the job's secrets.

### D6. The skip rule exempts the base branch

The job condition becomes `github.event_name != 'push' || github.ref_name == '<base>' || !contains(message, 'L4-Run: ')`.
The base is written as a GitHub expression string, with `'` doubled.

Why: a merge or archive commit on the base that carries the trailer must still run the sweeper. On GitLab this
already holds.

### D7. Resume by label on GitHub

- `label_events(n)`: `GET /repos/{o}/{r}/issues/{n}/events`, paginated, keeping `labeled` and `unlabeled` with the
  label name, the actor id and the time.
- `member_access(user_id)`: `GET /user/{id}` gives the login. Then `GET /repos/{o}/{r}/collaborators/{login}/permission`.
  The `role_name` maps to GitLab's levels: admin 50, maintain 40, write 30, triage 20, read 10. A 404 gives None.
- So the existing rule (level ≥ 30 may resume, `resume_label.py:62`) means GitHub write access, as its comment already
  says.

### D8. No check run is `not_run`, never green

When the hand-off commit has no check run, the sweeper records the repository-CI duty as `not_run`, with the reason
"no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs (use a token that does, or a
GitHub App)". It does not move to green.

### D9. Links and wording

- **Evidence link.** GitHub's evidence link is `<project>/blob/<ref>/<path>`; GitLab keeps `/-/blob/`.
- **PRV-001 human steps.** On GitHub they say "a secret of the GitHub environment `<ci.github_environment>`".
- **ENV-014.** On GitHub it says "the user the runner service runs as", not `gitlab-runner`.
- **How the platform is known.** From `cfg.ci.platform`, else the forge type.

### D10. The harness fetched at run time

**Config.** `harness.repository` is a git URL: `https://…`, `ssh://…`, or the scp form `git@host:owner/repo.git`,
which is normalised to `ssh://git@host/owner/repo.git`. With `harness.repository` set, `harness.commit` is required.

**Shim.** The shim (POSIX sh) of a fetched harness:
1. reads `repository` and `commit` from `.l4/config.yaml` with `sed`, so L4-INS-005's one place stays the only place;
2. checks the commit is 40 hex characters;
3. runs `exec uvx --python <pin> --from "git+<repository>@<commit>" l4 "$@"`.

uv caches the built tool environment under its cache, keyed by the commit. A second call does not fetch. On a hosted
runner the tool cache holds `~/.cache/uv`, and its key includes the pinned commit instead of the vendored files.

**Init and upgrade.**
- `l4 init --harness-repo URL [--harness-commit SHA]` writes no `.l4/vendor/`. The commit defaults to the running
  harness's own.
- `l4 upgrade --harness-commit SHA` rewrites only `harness.commit`, and re-renders the shim, the setup script and the
  CI file from the harness it runs as.
- `--vendor` stays for air-gapped runners and is the GitLab default until the GitLab template gets the key step.

**Private harness.**
- With an SSH `harness.repository`, the GitHub template writes the secret `L4_HARNESS_SSH_KEY` (an ed25519 key whose
  public half is a read-only deploy key on the harness repository) to `$RUNNER_TEMP/l4-harness-key` (0600).
- It pins GitHub's published SSH host keys in `$RUNNER_TEMP/l4-known-hosts`, taken from `api.github.com/meta` at
  render time and recorded in the template.
- It exports `GIT_SSH_COMMAND` through `$GITHUB_ENV`.
- `$RUNNER_TEMP` is added to the sandbox's runner-temporary paths (`runner_tmp_paths`), so no agent or gate can read
  the key.
- Without the secret the step does nothing, which suits a public harness over https.

**Traceability.** `buildinfo.harness_commit()` reads, in order:
1. the vendored `l4/_commit.py`;
2. a git checkout;
3. the installed package's `direct_url.json` (`vcs_info.commit_id`).

So the ledger names the harness commit in every mode.

**What the adopting repository keeps:**
- `.l4/config.yaml`, `.l4/bin/l4` and `.l4/bin/l4-setup`;
- the workflow;
- `.l4/prompts/` overrides;
- each spec's `.l4/ledger/`, `verification.md` and `questions.md`: the evidence.

Nothing of the harness itself.

Rejected alternatives:
- A wheel published to a package index. Hosting is undecided, and a private index needs its own credential.
- A git submodule. It still records the harness in the history as a gitlink, and every upgrade is a commit.

### D11. `l4 setup github`

`l4 setup github [--repo owner/name] [--token-env GH_TOKEN] [--secret NAME=ENV]... [--watch] [--dry-run]` uses a token
that has admin on the repository. The token's value is never printed. It is idempotent. It prints one row per step,
as `l4 setup gitlab` does (`KEPT | SET | CREATED | FAILED`).

Steps:
1. Check admin permission.
2. Set the workflow permissions (`default_workflow_permissions: write`, `can_approve_pull_request_reviews: true`).
3. Create or update the environment `ci.github_environment`, with a custom deployment branch policy: the base branch
   and the unit prefix patterns `<prefix>*` and `<prefix>**/*`.
4. Write each `--secret` into the environment, sealed with the environment's public key (PyNaCl, a new dependency).
5. Set the repository variable `L4_SELF_PROVISION` to `true` when `ci.runner_tags` is empty.
6. Create the labels.
7. Dispatch the `l4` workflow on the base branch, and follow it with `--watch`.

`--dry-run` sends only reads.

### D12. `l4 ci watch` on GitHub

`l4 ci watch --repo owner/name --ref main [--tail 60]` finds the newest run of `l4.yml` on the ref, polls until it
completes, prints each job's conclusion and the tail of a failed job's log through `Forge.job_log`, and exits 0 for
success, else 1. On GitLab, the same command keeps today's behaviour.

## SPEC amendments required by this change

1. L4-INS-004: `--vendor` is for air-gapped runners. L4-INS-001 and L4-INS-005 gain `harness.repository` and the
   fetched shim (D10). Q1 becomes "hosted: a private GitHub repository, fetched by commit".
2. L4-IMP-012: GitHub's job timeout comes from `L4_JOB_TIMEOUT_MINUTES` (D3).
3. §16.2: base checkout, skip rule, deadline env, continuation and deploy-key step (D3–D6, D10).
4. L4-CI-004: resume by label on GitHub (D7).
5. Hand-off repository CI: `not_run` without check runs (D8).
6. §15: PRV-001 and ENV-014 wording per platform (D9).
7. §21: delivery row 16 `github-parity`.
8. forge-and-ci tasks 1.14, 2.9 (collaborator permission) and 2.10 are delivered by this change.

## Risks

- **A public repository publishes its Actions logs and artifacts.** The harness's prompts and logs from a run are then
  public until the repository is deleted. The fetched harness keeps its source out of the repository, but not out of
  the logs. The dummy repository holds no secret and is deleted after the tests.
- **A deploy key is a standing credential.** It is read-only and scoped to one repository. It is removed from the
  harness repository after the dummy tests.
- **uvx needs the network on a cold cache.** An air-gapped runner keeps `--vendor`.
- **GitHub's deployment branch patterns.** Whether `<prefix>**/*` matches `l4/openspec/<unit>` is [U]. The live run
  checks it, and `l4 setup github` prints the patterns it set.
