## Purpose

Package the harness for adopters and agents: a GitHub setup action with two sources and split caches, a short
consumer workflow pinned by version, the harness repository's own CI and releases, and an installable `l4` skill. Every
piece is validated live.

## ADDED Requirements

### Requirement: L4-ACT-001 The harness is a setup action with two sources
The harness repository SHALL hold `.github/actions/l4/action.yml`, a composite action. It installs the harness, makes
the runner ready, and puts `l4` on `PATH`. It takes two sources:
- **`action`:** installs from the action's own downloaded copy, with no credential.
- **`repository`:** installs `git+<repository>@<commit>`. With `ssh-key`, the key goes to a 0600 file in
  `$RUNNER_TEMP`, used with GitHub's pinned host keys and removed right after the install.

`auto` picks `action` when the action's repository holds `src/l4`, else `repository`.

A bad `source`, a `commit` that is not 40 hex digits, or a missing `repository` MUST fail with `::error::` and exit 2
before any download. The action MUST never print an input value.

#### Scenario: SCN-ACT-01 (+) A private repository of the same owner needs no key
- **GIVEN** a private repository of the harness owner and the harness repository's Actions access `user`
- **WHEN** a job runs `uses: <owner>/agent-supervisor/.github/actions/l4@<sha>` and then `l4 --version`
- **THEN** the job succeeds with source `action` and no secret configured

#### Scenario: SCN-ACT-02 (−) A public repository cannot use the private action
- **GIVEN** a public repository
- **WHEN** a job uses the private action
- **THEN** the job fails at "Set up job" with `Unable to resolve action … not found` (as GitHub documents)

#### Scenario: SCN-ACT-03 (+) A public repository with a deploy key
- **GIVEN** a public repository with a copy of the action and `L4_HARNESS_SSH_KEY` in its environment `l4`
- **WHEN** the copy runs with source `repository`, the harness's SSH URL and a pinned commit
- **THEN** `l4 --version` succeeds, and the key file no longer exists after the install step

#### Scenario: SCN-ACT-04 (−) A bad commit stops before any download
- **GIVEN** source `repository` and `commit: main`
- **WHEN** the action runs
- **THEN** it fails with `::error::commit must be 40 hex digits` and exit 2, and fetched nothing

### Requirement: L4-ACT-002 The harness and the agent CLIs have separate caches
The action SHALL restore and save two caches:
- **The installed harness:** the uv tool directory, uv's Pythons, and the `l4`, `uv` and `uvx` links. It is keyed on
  the OS, architecture, image, Python, source, and the source's content hash or commit.
- **The agent CLIs and bwrap,** at the paths `doctor --ci --fix` installs into. They are keyed on the OS,
  architecture, image and a hash of the provisioning catalog's pinned versions.

The CLI key MUST NOT contain the harness commit or content hash. `clis: none` skips the second cache.

#### Scenario: SCN-ACT-05 (+) A warm job builds nothing
- **GIVEN** a previous job with the same harness source and catalog
- **WHEN** a job runs the action
- **THEN** both caches are hits, nothing is installed, and `l4 --version` follows the restore

#### Scenario: SCN-ACT-06 (+) A harness upgrade keeps the CLIs warm
- **GIVEN** warm caches for harness commit A
- **WHEN** the workflow moves to commit B with the same catalog
- **THEN** the harness cache misses and is rebuilt, the CLI cache hits, and `doctor --ci --fix` installs no CLI

### Requirement: L4-ACT-003 The runner setup runs inside the action
On GitHub the action SHALL run the harness's own `l4-setup.sh`:
- **source `action`:** from its copy;
- **source `repository`:** rendered by the installed harness.

It uses the same switch (`L4_SELF_PROVISION`, input `self-provision`, `auto` on disposable runners), the same single
root command, and the same `[HSU-nn]` lines as L4-PRV-020..022. A consumer in action mode MUST NOT need
`.l4/bin/l4-setup`.

#### Scenario: SCN-ACT-07 (+) The sandbox is ready on ubuntu-24.04
- **GIVEN** a GitHub-hosted ubuntu-24.04 job with the action and `self-provision: auto`
- **WHEN** the action runs
- **THEN** the log has `[HSU-99] OK summary` with bwrap usable, and the repository holds no `.l4/bin/` file

### Requirement: L4-ACT-004 `l4 init --action` writes a short workflow and one pin
`l4 init --ci github --action` SHALL write `harness.delivery: action` and a `.github/workflows/l4.yml` that keeps
github-parity's triggers, permissions, environment, concurrency, timeout and base-branch rule. Its steps are:
1. checkout;
2. `uses: <owner>/<repo>/.github/actions/l4@<sha> # <ref>`;
3. `l4 doctor --ci --fix`;
4. `l4 plan --sweep`;
5. `l4 run`;
6. `l4 status`;
7. upload `.l4-out`.

Further rules:
- It MUST NOT write `.l4/bin/l4`, `.l4/bin/l4-setup` or `harness.commit`. The `uses:` sha is the only pin.
- `--action-copy` writes the action under `.github/actions/l4` and uses it with source `repository`, for public
  callers.
- `--dependabot` adds or merges `.github/dependabot.yml` for `github-actions`.
- `l4 doctor` MUST check that the `uses:` line names a 40-hex sha and, for source `repository`, that its `commit`
  input matches it.

#### Scenario: SCN-ACT-08 (+) A fresh adoption holds only config, the workflow and evidence
- **GIVEN** a repository without L4
- **WHEN** `l4 init --ci github --action --harness-ref v0.3.0` runs
- **THEN** the new files are `.l4/config.yaml`, `.github/workflows/l4.yml` (with `uses: …@<sha> # v0.3.0`) and `.serena/project.yml`, and `l4 doctor` passes its pin check

#### Scenario: SCN-ACT-09 (−) A drifting pin is reported
- **GIVEN** an action-mode workflow with source `repository` whose `uses:` sha and `commit` input differ
- **WHEN** `l4 doctor` runs
- **THEN** the pin check fails and names both shas

### Requirement: L4-ACT-005 Pins name versions and move by pull request
`l4 init` and `l4 upgrade` SHALL accept `--harness-ref REF`.
- REF is resolved once with `git ls-remote`, and the sha is written as `@<sha> # <REF>`. A ref that resolves to
  nothing is exit 2.
- `l4 upgrade --harness-ref` or `--harness-commit` re-renders the workflow from the config with the template of the
  harness that runs it and the new pin (the `uses:` line, and the `commit` input of source `repository`); `--dry-run`
  writes nothing, and a second run changes nothing.

#### Scenario: SCN-ACT-10 (+) Upgrade by version
- **GIVEN** an action-mode workflow at `v0.3.0`
- **WHEN** `l4 upgrade --harness-ref v0.4.0` runs
- **THEN** the workflow is re-rendered from the config with the template of the harness that runs it and the new pin:
  the `uses:` line is `@<sha of v0.4.0> # v0.4.0`, older steps are replaced by the current ones, and a second run
  changes nothing

### Requirement: L4-ACT-006 Releases are slim commits on a release branch
The harness repository SHALL have `release.yml`. On a tag `src-vX.Y.Z` it MUST:
1. build a commit on branch `release`, holding only `src/`, `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE` (when
   present), `.github/actions/l4/` and `skills/`. Its parent is the previous release commit, and its message names the
   source sha;
2. check that its tree equals a `git archive` of those paths at the source sha;
3. tag it `vX.Y.Z` and move `v0`;
4. create a GitHub release naming the source sha.

#### Scenario: SCN-ACT-11 (+) One release
- **GIVEN** a tag `src-v0.3.0` on a commit whose checks passed
- **WHEN** `release.yml` runs
- **THEN** `release` gains one commit with only those paths, `v0.3.0` and `v0` point to it, and the release names the source sha

### Requirement: L4-ACT-007 The harness repository tests itself
`checks.yml` SHALL run the unit suite in 8 deterministic shards on pull requests to `amaster`, nightly when `amaster`
moved, and on `workflow_dispatch`. A summary job fails when any shard fails.

`action-selftest.yml` MUST run `uses: ./.github/actions/l4` with source `action`, then `l4 --version` and
`l4 doctor --adoption` on `tests/fixtures/py_tdd`. `.github/dependabot.yml` covers the repository's own
`github-actions` pins.

#### Scenario: SCN-ACT-12 (−) A failing shard fails the check
- **GIVEN** a pull request with one failing unit test
- **WHEN** `checks.yml` runs
- **THEN** exactly that shard fails, and the summary job fails

### Requirement: L4-SKL-001 An installable `l4` skill
The harness repository SHALL hold `skills/l4/SKILL.md` in the Agent Skills format:
- frontmatter `name: l4`;
- a description that starts "Use when…" and names the triggers (adopting L4, a unit's status, questions, feedback, an
  escalated or halted unit);
- a body under 500 words.

Its reference files are `adopt.md`, `operate.md` and `feedback.md`. `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` MUST make it installable with `/plugin marketplace add` and `/plugin install`. The
skill MUST never ask for, print or move a secret, and never tells an agent to run agent CLIs by hand on a runner.

#### Scenario: SCN-SKL-01 (+) Installed from the repository
- **GIVEN** a Claude Code session with read access to the harness repository
- **WHEN** the person runs `/plugin marketplace add ciprianiacobescu/agent-supervisor` and `/plugin install l4@agent-supervisor`
- **THEN** the skill `l4` is listed and loads

### Requirement: L4-SKL-002 The skill is written against recorded failures
Before the skill is written, subagents without it SHALL attempt the scenarios of design D8, and their answers are
recorded in `skills/l4/tests/baseline.md`. The same scenarios MUST then be run with the skill, with the outcomes in
`skills/l4/tests/with-skill.md`. Every scenario that applies MUST pass, and any loophole found is closed and re-run.

#### Scenario: SCN-SKL-02 (+) The feedback kind is chosen right
- **GIVEN** the request "the base URL is hard-coded; make it configurable"
- **WHEN** an agent with the skill turns it into a command
- **THEN** it runs `l4 feedback add --kind config --env <NAME> --at <file:line> --text …`, not `refactor`

#### Scenario: SCN-SKL-03 (−) A refactor that breaks tests is not sent as refactor
- **GIVEN** the request "rename `calc` to `compute`; the tests call `calc`"
- **WHEN** an agent with the skill chooses the kind
- **THEN** it chooses `behaviour`, with `--when`/`--then`, and says why

### Requirement: L4-ACT-008 Validated live
Each requirement SHALL be proven on GitHub, with run ids and Actions API step timings, under `docs/live/action/`:
- both sources, private and public;
- the split caches across a harness upgrade;
- `l4 init --action` on a fresh copy;
- a full `doctor`/`plan`/`run` of a seed unit through the action;
- one release;
- one sharded pull-request check.

Temporary deploy keys MUST be removed after their test.

#### Scenario: SCN-ACT-13 (+) A seed unit end to end through the action
- **GIVEN** the dummy repository adopted with `l4 init --action` and one seed unit
- **WHEN** the workflow runs on a push
- **THEN** the unit reaches a ready PR, and the step timings show a warm job's action step under 15 s with both caches hit
