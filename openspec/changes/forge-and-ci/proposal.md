## Why

The harness is only useful once a maintainer can add it to an existing repository with one or two commands and see
real merge requests, labels and pipelines appear. This change delivers the outward-facing half: the forge clients
that open and mirror PRs/MRs, the generated CI for GitLab 17.5.2 CE and GitHub Actions, `l4 init` that adopts the
harness in a repo, and the archive lifecycle that turns a merged unit into archived specs. It implements SPEC
section 1 (INS), section 11 (ARC) and section 16 (CI) and is change 9 of the delivery plan. L4-RACE-001 (also in section 11)
is owned by `state-vcs-locks`; the archive paths here consume it.

The reference runner `l4-runner` (id 12) has `run_untagged: false` and a shell executor, and a `: ` inside a
plain YAML `script:` item breaks GitLab pipelines (lessons already paid for, implementation map). Generated CI
therefore carries explicit tags and calls only a shim script or one-line `l4 ...` commands.

## What Changes

- Add `l4 init [--ci github|gitlab|both] [--framework openspec|kiro] [--vendor] [--dry-run] [--force]`: writes the
  exact file set of L4-INS-002, detects framework and ecosystem gates, pins `harness.version` + `harness.commit`
  once, bootstraps OpenSpec on request, vendors the harness for air-gapped runners.
- Add the `Forge` port with GitLab (REST v4 via httpx, project access token), GitHub and local implementations:
  draft MR/PR, labels, sticky note, commit status, pipeline job listing, member check, approvals, trigger dispatch.
- Add CI rendering: `l4 ci render`, `l4 ci render-child` (handlers `l4.ci.commands:run_render`, `run_render_child`; `l4 ci map-exit` is bootstrap-core's real command and is only called from the templates); GitLab include template + dynamic child
  pipeline (tags, `resource_group`, `interruptible: false`, `|| l4 ci map-exit $?`, `[skip ci]` checkpoints, hand-off
  commit without skip) and a GitHub Actions workflow at parity; the `.l4/bin/l4` shim that fetches the harness by
  pinned commit SHA.
- Add counted continuation dispatch and the scheduled sweeper duties of SPEC 16.4.
- Add `src/l4/archive.py`: the single hand-off commit, PR title/body/labels/status mirror, repository-CI evaluation,
  post-merge archive PR (default, serialised), archive-on-approval (opt-in) with revert/re-archive, abandoned/reopen
  handling; archive and hand-off pushes go through `state-vcs-locks`' race handling (`l4.vcs.push`, L4-RACE-001).
- Add doctor checks `CI-001..004` and `FORGE-001..004` (FORGE-005/006 stay in `state-vcs-locks`).

## Capabilities

### New Capabilities

- `install-init`: package identity, zero-install execution, `l4 init` file set, dry-run diff, no-overwrite, framework
  and gate detection, OpenSpec bootstrap, `--vendor`, single version pin and drift detection.
- `ci-integration`: GitLab CI template (17.5.2 CE) and GitHub Actions workflow, exit-code plumbing, loop safety,
  push credentials, untrusted events, counted continuation, sweeper.
- `archive`: hand-off invariant, PR/MR lifecycle and mirrors, post-merge archive PR, archive on approval, base-move
  refresh, abandon/reopen, race-safe pushes.

### Modified Capabilities

None.

## Impact

Owned source paths (implementation-map layout; extra modules live inside the owned packages):

- `src/l4/forge/base.py`, `src/l4/forge/gitlab.py`, `src/l4/forge/github.py`, `src/l4/forge/local.py`
- `src/l4/ci/router.py`, `src/l4/ci/render.py`, `src/l4/ci/templates/`; additional modules `src/l4/ci/commands.py`,
  `src/l4/ci/lint.py`, `src/l4/ci/continuation.py`, `src/l4/ci/sweeper.py`
- `src/l4/init/init.py`, `src/l4/init/templates/`; additional modules `src/l4/init/ecosystem.py`,
  `src/l4/init/pin.py`, `src/l4/init/vendor.py`, `src/l4/init/ciedit.py`
- `src/l4/archive.py`
- `src/l4/doctor/checks_ci.py`, `src/l4/doctor/checks_forge.py`
- tests: `tests/unit/forge/`, `tests/unit/ci/`, `tests/unit/init/`, `tests/unit/archive/`, `tests/contract/test_forge_contract.py`,
  `tests/fixtures/gitlab/`, `tests/fixtures/ci/`

Depends on `bootstrap-core` (config models, CLI group, exit codes, doctor registry, redaction), `spec-providers`
(`SpecProvider.done_gate/archive/validate`, detection), `state-vcs-locks` (hardened git runner, trailers, push
classification, ledger, lifecycle) and `simulation-harness` (the fake forge implements the same `Forge` protocol and
runs the conformance suite). Consumed by `implementer-tdd-loop` (orchestrator calls hand-off and mirror) and
`live-validation`.
