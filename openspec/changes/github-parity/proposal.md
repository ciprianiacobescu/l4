## Why

On GitHub the harness has the core pull-request loop: a draft PR, then ready, plus labels, check runs and push
credentials. A full `l4 run` on a GitHub repository with GitHub-hosted runners has never worked, and several pieces
are missing or wrong. These facts come from a parity survey of the code on 2026-10-11 [V, code]:

- **The workflow's own token cannot be the forge token today.**
  - Sticky notes call `GET /user` (`forge/github.py:397`), which `GITHUB_TOKEN` may not call, so no note ever reaches
    the PR.
  - A repository that does not let Actions create pull requests answers 403 to `create_pr`, and the run ends with exit 3
    and no hint (`archive.py:163, 302`).
- **No soft deadline on GitHub.** `job_remaining_s` reads only GitLab's `CI_JOB_TIMEOUT` (`orchestrator.py:1145`).
  With `time_budget: auto`, a GitHub job is killed at `timeout-minutes` with no clean stop.
- **No continuation.** `ci.continuation` is never read (`schema.py:590`). Leftover units wait for the next push or the
  30-minute schedule. This holds on GitLab too.
- **Resume by label never works on GitHub.** `label_events`, `member_access` and `own_user_id` are stubs
  (`github.py:365-373`).
- **A unit-branch push runs the harness from the pushed branch.** GitLab's template checks out the base branch first
  (`l4.gitlab-ci.yml:39`); GitHub's does not. This is a security gap.
- **The `L4-Run:` skip also skips the base branch** on GitHub (`l4.github.yml:21`). GitLab exempts it.
- **A hand-off with no check runs reports green** (`sweeper.py:546-549`). With `GITHUB_TOKEN`, pushes start no
  workflow runs, so "green" is wrong.
- **The PR body's evidence link uses GitLab's `/-/blob/` path** (`archive.py:95`).
- **No `l4 setup github` and no `l4 ci watch` for GitHub.** The adoption steps are manual (`quickstart.md` §4).
- **GitLab wording on GitHub.** PRV-001 and ENV-014 hints speak of "masked CI variables" and `gitlab-runner`
  (hosted-runner-setup task 2.5).
- **The harness is committed into every adopting repository.** `l4 init --vendor` copies it into `.l4/vendor/`, so
  every upgrade lands in the repository's history. For a public repository it would also publish a private harness.
  The SPEC's own design (L4-INS-001, L4-INS-005) is to fetch the pinned commit at run time. That branch of the shim was
  never built (forge-and-ci 1.14; SPEC Q1).

The maintainer asked for feature parity on GitHub, proven on a public dummy repository that is deleted after the
tests. They also asked whether the harness can be pulled at run time and cached, so that it never enters the
repository's history and only the evidence folders stay.

## What Changes

**M1: a full run on GitHub-hosted runners with the workflow's own token.**
- **`GITHUB_TOKEN` as the forge token.**
  - When `GET /user` is refused inside Actions, the forge knows itself as `github-actions[bot]` (id 41898282 [V]). Its
    sticky note is found and updated.
  - A 403 on `create_pr` names the repository setting that allows Actions to create pull requests.
- **The soft deadline.** The template passes `L4_JOB_TIMEOUT_MINUTES`, equal to the job's `timeout-minutes`, and the
  harness reads it like `CI_JOB_TIMEOUT`.
- **Continuation by `workflow_dispatch`.** A run that stops for the deadline with units left dispatches the `l4`
  workflow on the base branch once. It does not when a run is already queued. GitHub always starts a run for a
  `workflow_dispatch` made with `GITHUB_TOKEN` [D].
- **Template security parity.**
  - A push to any branch other than the base runs the harness and config of the base branch, as on GitLab.
  - The `L4-Run:` skip exempts the base branch.
- **Resume by label.** GitHub's `label_events` (issue events), `member_access` (collaborator permission mapped to
  GitLab's levels) and `own_user_id` are implemented.
- **Honest hand-off CI.** No check run at the hand-off commit is `not_run`, with the reason, never green.
- **The right evidence link** on GitHub.
- **GitHub wording** for PRV-001 and ENV-014. This absorbs hosted-runner-setup task 2.5.
- **The harness is fetched at run time, not committed.**
  - `harness.repository` joins `harness.commit` in the config.
  - The shim runs `uvx --python <pin> --from git+<repository>@<commit> l4`.
  - `l4 init --harness-repo URL` writes no `.l4/vendor/`.
  - The GitHub template installs a read-only deploy key from the secret `L4_HARNESS_SSH_KEY` when the repository URL is
    SSH, and keys the tool cache on the pinned commit, so a warm job fetches nothing.
  - `l4 upgrade --harness-commit SHA` moves the pin.
  - The repository then keeps only `.l4/config.yaml`, `.l4/bin/l4`, `.l4/bin/l4-setup`, the workflow file and the
    evidence folders: each spec's `.l4/ledger/`, `verification.md` and `questions.md`.
  - `--vendor` stays, for air-gapped runners.
- **`l4 setup github`.** In one idempotent command it sets up:
  - the environment `ci.github_environment`, with a deployment branch policy for the base branch and the unit prefix;
  - its secrets, from `--secret NAME=ENV`;
  - the variable `L4_SELF_PROVISION`;
  - the workflow permissions (write, and Actions may create pull requests);
  - the labels;
  - a dispatched check run, followed with `--watch`.
- **`l4 ci watch` on GitHub.** It follows the latest run of the `l4` workflow on a ref.
- **Live evidence** on a public dummy GitHub repository, deleted after the tests.

**Not in this change:** GitHub App token minting (forge-and-ci 2.11), commit statuses, approvals and `merge_policy`
(missing on both forges), `render-child`, and continuation on GitLab (forge-and-ci 2.6).

## Capabilities

### New Capabilities

- `github-parity`: the workflow token as forge token, the GitHub soft deadline and continuation, the base-branch
  harness on other branches, resume by label, honest hand-off CI, the harness fetched at run time, `l4 setup github` and
  `l4 ci watch` on GitHub.

### Modified Capabilities

None as an OpenSpec delta. design.md lists the SPEC lines this change amends: L4-INS-004/005, L4-IMP-012, L4-CI-004,
§16.2, and the forge-and-ci tasks 1.14, 2.9 (part) and 2.10 it completes.

## Impact

- Code:
  - `src/l4/forge/github.py` and `base.py`: identity, the label, member and continuation methods, the 403 message.
  - `src/l4/archive.py`: the evidence link.
  - `src/l4/ci/github.py` and `templates/l4.github.yml`: deadline env, base checkout, skip rule, deploy key, cache key.
  - `src/l4/orchestrator.py`: the deadline and the continuation.
  - `src/l4/ci/sweeper.py`: `not_run`.
  - `src/l4/ci/render.py`: the uvx shim.
  - `src/l4/init/*`: `--harness-repo`.
  - `src/l4/buildinfo.py`: the commit of a fetched harness.
  - `src/l4/config/schema.py`: `harness.repository`.
  - `src/l4/setup/github.py` and `src/l4/ci/watch.py`.
  - `src/l4/provision/readiness.py` and `src/l4/doctor/checks_agents.py`: wording.
- Docs: `docs/SPEC.md`, `docs/quickstart.md` (GitHub becomes `l4 setup github`), `docs/live/` (the GitHub run).
- Live: a public dummy repository under the maintainer's account, created and deleted by the harness maintainer's
  tooling. A read-only deploy key on the private harness repository is removed after the tests.
