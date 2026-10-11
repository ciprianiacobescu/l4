## Purpose

Let the `l4` job run on a runner nobody prepared (a GitHub-hosted VM), switched by one flag: bootstrap uv before the
shim, give the job user a working bwrap with at most one root command on a disposable runner, cache the tools between
jobs, and let the paid agent CLIs authenticate from secrets alone. Evidence: `docs/spikes/06-hosted-runner-setup.md`.

## ADDED Requirements

### Requirement: L4-PRV-019 Environment override of self-provisioning
`resolve_self_provision(cfg, env)` SHALL read the environment variable `L4_SELF_PROVISION` before `ci.self_provision`.
The values `true`, `false` and `auto` (in any letter case) MUST replace the configured value. Any other value MUST be
ignored with one warning line that names the variable and the value it ignored, and the configured value then applies.
`auto` MUST keep its meaning (false on a disposable runner, else true).

#### Scenario: SCN-PRV-55 (+) The variable turns provisioning on for a hosted runner
- **GIVEN** `ci.self_provision: auto`, `RUNNER_ENVIRONMENT=github-hosted` and `L4_SELF_PROVISION=TRUE`
- **WHEN** `l4 doctor --ci --fix` runs with an agent CLI missing
- **THEN** the CLI is installed user-locally and its fix line says `applied`

#### Scenario: SCN-PRV-56 (−) The variable turns provisioning off whatever the config says
- **GIVEN** `ci.self_provision: true` and `L4_SELF_PROVISION=false`
- **WHEN** `l4 doctor --ci --fix` runs with an agent CLI missing
- **THEN** every install action is `skipped`, nothing is written under `~/.local` and ENV-004 keeps failing

#### Scenario: SCN-PRV-57 (−) An unknown value is ignored with a warning
- **GIVEN** `ci.self_provision: false` and `L4_SELF_PROVISION=yes`
- **WHEN** provisioning is resolved
- **THEN** one warning names `L4_SELF_PROVISION` and `yes`, and the result is false (the config)

### Requirement: L4-PRV-020 A setup step before the first l4 command
`l4 init` and `l4 upgrade` SHALL write the executable `.l4/bin/l4-setup` next to the shim. It acts on
`L4_SELF_PROVISION` alone, because it cannot read the config:
- `true` acts;
- `auto` acts only on a runner that is not disposable, as `resolve_self_provision` does;
- any other value, unset included, does not act.

When it acts, it MUST install the harness's pinned uv into `~/.local/bin` when uv is absent, with
`UV_NO_MODIFY_PATH=1` and no shell profile edit. On GitHub it MUST append `~/.local/bin` to `$GITHUB_PATH`. It MUST print
one `[HSU-nn] STATUS title — detail` line per step and never print or read a credential value. With the flag not true,
it MUST print exactly one `SKIP` line and change nothing. It exits 2 only when uv cannot be installed.

#### Scenario: SCN-PRV-58 (+) A bare hosted image gets uv
- **GIVEN** a GitHub-hosted `ubuntu-24.04` job with no uv and `L4_SELF_PROVISION=true`
- **WHEN** `.l4/bin/l4-setup` runs
- **THEN** `~/.local/bin/uv --version` prints the pinned version, `$GITHUB_PATH` contains `~/.local/bin`, and the next step's `.l4/bin/l4 --version` succeeds

#### Scenario: SCN-PRV-59 (−) Flag off changes nothing
- **GIVEN** a hosted job with `L4_SELF_PROVISION` unset and `auto` in the config
- **WHEN** `.l4/bin/l4-setup` runs
- **THEN** it prints one line `[HSU-00] SKIP hosted setup — ...`, and no file appears under `~/.local/bin` or `$L4_HOME`

### Requirement: L4-PRV-021 User-space bwrap
When the flag resolves true, `l4-setup` SHALL give the job user a bwrap that passes the self-test `bwrap --ro-bind / /
--dev /dev --proc /proc --unshare-user --unshare-pid --die-with-parent true`, without root. The user-space binary is
`$L4_HOME/bwrap/usr/bin/bwrap`, linked from `~/.local/bin/bwrap`.
- A user-space binary that passes MUST be kept (`already present`, no download).
- When there is no user-space binary and another bwrap on PATH passes, nothing is installed.
- When there is no user-space binary, it is obtained with `apt-get download bubblewrap` into a temporary directory and
  `dpkg -x` into `$L4_HOME/bwrap`. Without `apt-get` or `dpkg` it MUST report `manual` and continue.
- A user-space binary that exists but fails MUST NOT be downloaded again. It goes to the root step (L4-PRV-022).
- A link to a binary that fails MUST be removed, so it cannot shadow a working system bwrap.

#### Scenario: SCN-PRV-60 (+) Ubuntu 22.04 needs no root
- **GIVEN** a GitHub-hosted `ubuntu-22.04` job with the flag on
- **WHEN** `l4-setup` runs
- **THEN** the user-space bwrap passes the self-test, no `sudo` command is run, and doctor's sandbox checks pass

#### Scenario: SCN-PRV-61 (+) A cached bwrap is not fetched again
- **GIVEN** `$L4_HOME/bwrap/usr/bin/bwrap` restored from the tool cache and passing the self-test
- **WHEN** `l4-setup` runs
- **THEN** its bwrap line says `already present` and no `apt-get download` runs

### Requirement: L4-PRV-022 The one root step, on disposable runners only
`l4-setup` SHALL run at most one root command, `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. It MUST run
it only when all of these hold:
- the runner is disposable (`RUNNER_ENVIRONMENT=github-hosted` or `CI_DISPOSABLE_ENVIRONMENT=true`);
- `sudo -n true` succeeds, or the user is root;
- `L4_PROVISION_ROOT` is not `0`;
- the user-space bwrap failed its self-test;
- the setting reads `1`.

The conditions are checked in the order bwrap, disposable, opt-out, setting. The sudo check (`sudo -n true`, unless
the user is root) comes last, so no other case runs `sudo`. It MUST then run the self-test again and log the setting's old and new values. It MUST NOT run `apt-get install` or any
other root command. In every other case it MUST print the exact command with the reason it was not run. `l4 doctor
--fix` MUST NOT run any root command (L4-DOC-002 is unchanged).

#### Scenario: SCN-PRV-62 (+) Ubuntu 24.04: one sysctl, then the user-space bwrap works
- **GIVEN** a GitHub-hosted `ubuntu-24.04` job, the flag on, the setting at 1 and the user-space bwrap failing with `setting up uid map: Permission denied`
- **WHEN** `l4-setup` runs
- **THEN** the only root command is the sysctl, after one `sudo -n true` check; the setting reads 0, the user-space bwrap passes, and no package is installed

#### Scenario: SCN-PRV-63 (−) A persistent runner never escalates
- **GIVEN** a GitLab shell-executor job (`CI_DISPOSABLE_ENVIRONMENT` unset, no `RUNNER_ENVIRONMENT`), passwordless sudo, the flag on and bwrap failing
- **WHEN** `l4-setup` runs
- **THEN** no `sudo` command runs, not even `sudo -n true`; the line prints the sysctl command and says the runner is not disposable, and doctor's sandbox check fails as before

#### Scenario: SCN-PRV-64 (−) The opt-out is honoured
- **GIVEN** the 24.04 hosted job of SCN-PRV-62 with `L4_PROVISION_ROOT=0`
- **WHEN** `l4-setup` runs
- **THEN** no `sudo` command runs and the line names `L4_PROVISION_ROOT=0`

### Requirement: L4-PRV-023 The hosted job and its tool cache
When `ci.runner_tags` is empty (hosted runner), the GitHub template SHALL:
- set `L4_SELF_PROVISION: ${{ vars.L4_SELF_PROVISION || '<rendered>' }}`, where `<rendered>` is `true` when
  `ci.self_provision` is `true`, else `auto`;
- restore a tool cache before `.l4/bin/l4-setup`;
- run `l4-setup`, then `l4 doctor --ci --fix`, `plan --sweep` and `run` as today;
- save the cache after doctor, only when every earlier step succeeded, the restore missed and the job runs on the base
  branch.

Both cache actions MUST be pinned by commit, like the template's other actions. The cache MUST cover exactly these paths:
- `~/.local/bin`;
- `$L4_HOME`;
- `~/.local/share/claude`;
- `~/.local/share/uv`;
- `$L4_CACHE`;
- `~/.cache/uv`.

It MUST NOT cover any credential path of `sandbox.credential_paths`. The key MUST include the runner OS and architecture,
the image name, and a hash of the vendored `catalog.py` and `l4-setup.sh`.

#### Scenario: SCN-PRV-65 (+) A warm job installs nothing
- **GIVEN** a cache saved by an earlier successful job with the same key
- **WHEN** the next hosted job runs
- **THEN** every `fix` line of `doctor --ci --fix` says `already present`, and no installer is downloaded

#### Scenario: SCN-PRV-66 (−) Credentials are never cached
- **GIVEN** the rendered GitHub template
- **WHEN** its cache paths are compared with `sandbox.credential_paths`
- **THEN** no cache path equals or contains a credential path (`~/.claude`, `~/.codex`, `~/.kiro`, `~/.local/share/opencode`, `~/.local/share/kiro-cli`, ...)

### Requirement: L4-PRV-024 Agent credentials from the environment
For claude-code, codex and kiro-cli profiles, the harness SHALL deliver the profile's own credential variable, and no
other profile's, to that profile's availability probe and agent process:
- claude-code: `CLAUDE_CODE_OAUTH_TOKEN` for `auth: subscription`, `ANTHROPIC_API_KEY` for `auth: api_key`;
- codex: `CODEX_API_KEY` for `auth: api_key`; a subscription profile gets none;
- kiro-cli: `KIRO_API_KEY`, for `auth: subscription` or `api_key`.

**Probe.** The variable goes into the probe's process environment. When it is set, the auth step MUST pass without
running a status or login command (`auth_method: env`), and the hello step proves the credential.

**Agent process.** The value MUST NOT appear in any argv, including bwrap's `--setenv` list. It is written to a new 0600
file in the step's private directory. A `/bin/sh` loader inside the sandbox reads it, deletes the file, exports the
variable and execs the agent. The harness removes the file after the step.

**Always:**
- The value MUST be redacted from every log, ledger and artifact.
- Codex `auth: api_key` MUST be probed, not refused.
- No login, token or account command is run (L4-PRV-007).
- When the variable is unset or empty, the probe line and PRV-001 MUST name it, in the form
  `<profile>: <VARIABLE> is not set`.

#### Scenario: SCN-PRV-67 (+) A secret alone authenticates Claude Code on a hosted runner
- **GIVEN** a hosted job with the flag on and `CLAUDE_CODE_OAUTH_TOKEN`, a secret of the job's GitHub environment, in the job environment
- **WHEN** `l4 probe` runs for a claude-code profile with `auth: subscription`
- **THEN** its auth and hello steps pass, and the token's value appears in no output file

#### Scenario: SCN-PRV-68 (−) A missing secret is named
- **GIVEN** a codex profile with `auth: api_key` and no `CODEX_API_KEY`
- **WHEN** `l4 probe` runs
- **THEN** the codex line reads `[l4] probe: codex skipped — auth: CODEX_API_KEY is not set`, and not "api_key is not supported"

#### Scenario: SCN-PRV-69 (−) Another profile's credential does not leak
- **GIVEN** `KIRO_API_KEY` and `CODEX_API_KEY` both set
- **WHEN** a kiro-cli agent step runs in the sandbox
- **THEN** the agent process has `KIRO_API_KEY` and not `CODEX_API_KEY`, and neither value is in bwrap's argv or in the environment the harness hands bwrap

### Requirement: L4-PRV-025 Pinned harness Python
The shim SHALL run the vendored harness with the Python version the harness pins (`uv run --python <pin>`). It MUST NOT
use the newest interpreter uv happens to find or download.

#### Scenario: SCN-PRV-70 (+) A hosted image with an old Python runs the pinned one
- **GIVEN** a GitHub-hosted `ubuntu-22.04` job (system Python 3.10)
- **WHEN** `.l4/bin/l4 doctor --ci` runs
- **THEN** ENV-001 reports the pinned Python version, not a newer one

### Requirement: L4-PRV-026 The setup is evidenced on real hosted runners
The change SHALL keep a workflow that runs the setup on GitHub-hosted `ubuntu-24.04` (cold and warm) and records the
setup lines, doctor's fix table, the probe lines and one agent call inside the harness's sandbox as artifacts. It MUST
NOT use a forge token. It MUST NOT push. It MUST run only on `spike/**` branches or by hand.

#### Scenario: SCN-PRV-71 (+) The evidence run passes
- **GIVEN** the workflow on a `spike/**` branch
- **WHEN** it runs
- **THEN** both jobs succeed, the OpenCode free-model call inside the sandbox answers `OK`, and `l4 simulate --all` reports 0 failed

### Requirement: L4-PRV-027 Pipeline secrets in a GitHub Environment
The generated GitHub job SHALL declare `environment: <ci.github_environment>` when that key is set (default `l4`),
hosted or self-hosted. The forge token and the agent credentials are then read as secrets of that environment. When
the key is null, the job MUST have no `environment:` key.

A GitHub secret reaches a job only when the job's `env` names it. So the job's `env` SHALL map, as
`NAME: ${{ secrets.NAME }}`, the forge token and the credential variable of every profile that a role chain uses:
- the L4-PRV-024 variable of claude-code, codex and kiro-cli profiles;
- `options.provider.api_key_env` of an opencode profile with a custom provider.

It MUST NOT map any other secret. When no role chain uses such a profile, the `env` is the forge token alone, as before
this change.

#### Scenario: SCN-PRV-72 (+) The default reads secrets from the `l4` environment
- **GIVEN** a config without `ci.github_environment`
- **WHEN** `l4 init --ci github` renders the workflow
- **THEN** the `l4` job has `environment: "l4"`, and its env still names `${{ secrets.<forge.token_env> }}`

#### Scenario: SCN-PRV-73 (−) Null turns it off
- **GIVEN** `ci.github_environment: null`
- **WHEN** the workflow is rendered for a self-hosted runner
- **THEN** it has no `environment:` key and is byte-identical to the rendering before this change

#### Scenario: SCN-PRV-74 (+) Exactly the chains' credential secrets reach the job
- **GIVEN** roles whose chains use a claude-code subscription profile and a codex api_key profile, and an unused kiro-cli profile
- **WHEN** the workflow is rendered
- **THEN** the job env maps `L4_FORGE_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` and `CODEX_API_KEY` from `secrets`, and not `KIRO_API_KEY`
