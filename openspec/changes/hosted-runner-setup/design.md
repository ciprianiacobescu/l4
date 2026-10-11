## Context

Evidence for everything labelled [V] is `docs/spikes/06-hosted-runner-setup.md`: GitHub Actions run 38144352581, with jobs
114484478622 (`ubuntu-24.04`, cold), 114484478868 (`ubuntu-22.04`, cold) and 114484850081 (`ubuntu-24.04`, warm). The
prototype was `scripts/runner/hosted-setup.sh` (commit 1c45eac of branch `spike/hosted-agent-setup`); task 1.2 replaced it
with `src/l4/ci/templates/l4-setup.sh`.

- [V] Both hosted images set `RUNNER_ENVIRONMENT=github-hosted`. This answers runner-provisioning design's "confirm in
  spike 19". Jobs run as `runner` with passwordless sudo. The images have git 2.55.0, Node 22.23.3 and `unzip`, and they
  have no uv and no bwrap. Python is 3.12.3 on 24.04 and 3.10.12 on 22.04.
- [V] Ubuntu 22.04 runs a user-space bwrap 0.6.1 (`apt-get download` + `dpkg -x`) as `runner` with no root.
- [V] Ubuntu 24.04 behaves differently:
  - With `kernel.apparmor_restrict_unprivileged_userns=1`, the user-space bwrap 0.9.0 and the apt-installed
    `/usr/bin/bwrap` both fail with `setting up uid map: Permission denied`.
  - `/etc/apparmor.d` has no bwrap profile.
  - After `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, the user-space binary passes.
- [V] `doctor --ci --fix` with the override installed OpenSpec 1.14.0, claude 2.1.288, codex 0.160.0, opencode 1.18.34 and
  kiro-cli 2.29.1 in 41–44 s; it took 7 s from the cache (every action `already present`). ENV-001..004 pass.
- [V] The OpenCode free model `opencode/mimo-v2.6-flash-free` answered the probe hello and answered one call inside the
  harness's bwrap (`select_sandbox` plus an agent `SandboxSpec`). The call was a standalone script, not the adapter's
  argv.
- [V] `l4 simulate --all` gives 5 passed, 0 failed, 16 pending, as locally.
- [V] On 22.04, ENV-001 reported Python 3.14.8: uv provisioned a newer interpreter for the vendored harness. The
  persistent GitLab runner drifts too: its vendored harness reports Python 3.13.16 (ENV-001,
  `docs/live/kiro-e2e/h2/ci/job-6146.log`), while CI's checks and `prereqs.sh` PRQ-06 use 3.12.
- [I, code] `availability/probes.py:75` refuses `api_key` profiles. The probe and sandbox environments forward no
  credential variable, and no probe line names a missing variable. `l4.sandbox.env.build_agent_env` forbids `--setenv`
  for a credential, because bwrap's argv is readable by any local user.
- [V] Claude Code authenticates from `CLAUDE_CODE_OAUTH_TOKEN` alone on both hosted images (run 38156758955, jobs
  114521218781 and 114521218926):
  - `claude auth status` reports `loggedIn: true, authMethod: oauth_token`;
  - `claude -p` answered OK outside the sandbox, and inside the harness's bwrap. Inside, the token came from a 0600 file
    through a `/bin/sh` loader and was in neither bwrap's argv nor its environment;
  - no artifact held the value;
  - `l4 probe` still said `claude is not logged in`, because the probe drops the variable.
- [V] GitHub Environments work on this private repository on the Free plan (2026-10-11):
  - environment `hosted-agents` holds `CLAUDE_CODE_OAUTH_TOKEN`, deployable from `spike/*` only;
  - environment `publication` holds `L4_PUBLICATION_RULES`;
  - the repository has no repository-level secret left.
- [D] GitHub deprecates the ubuntu-22.04 image with brownouts from 2026-09-17 and removes it on 2027-04-17.

## Goals

- One flag turns a bare hosted runner into a working L4 runner. Off means nothing changes.
- The flag can be switched without a commit (repository or organisation variable) and from the config.
- No root on any persistent runner, ever. On a disposable runner, at most one root command, only when it is needed and
  only with an opt-out.
- A cached job pays seconds, not minutes.
- Claude Code, Codex and Kiro can authenticate from secrets alone, with no login command.
- Pipeline secrets are secrets of a GitHub Environment, not repository secrets.

## Non-Goals

- GitLab Docker or Kubernetes executors: an unprivileged container cannot create user namespaces, so no bwrap works
  there [V, rehearsal].
- A full `l4 run` against a GitHub forge (change 13 `live-validation`).
- Installing anything with apt, and pinning bwrap's version: it is the distribution's package, and its version is
  recorded.
- `sandbox.mode: none` as the hosted default.
- Windows and macOS hosted runners.

## Decisions

### D1. The flag and its precedence

`resolve_self_provision(cfg, env)` reads `L4_SELF_PROVISION` first.

- Values: `true`, `false` or `auto`, case-insensitive.
- Any other value is ignored with a warning line, and the config applies.
- `auto` keeps its meaning: false on a disposable runner, else true. A hosted runner therefore needs `true` explicitly,
  so nothing is ever installed there by accident.

The GitHub template renders `L4_SELF_PROVISION: ${{ vars.L4_SELF_PROVISION || '<rendered>' }}`, where `<rendered>` is
`true` when `ci.self_provision` is `true` and `auto` otherwise. On GitLab, a project or group CI/CD variable of the same
name does the same.

Rejected: a second config key such as `ci.hosted_setup`. Two keys for one decision would drift apart.

### D2. A separate pre-shim script owns the bootstrap and the one root step

The shim cannot start without uv, so uv has to come from something that is not the harness. `.l4/bin/l4-setup` is a
POSIX-sh/bash script, vendored next to the shim. It prints one `[HSU-nn] STATUS title — detail` line per step, in the
style of `prereqs.sh`, and never reads or prints a credential. The root step lives here and never in `doctor --fix`, so
L4-DOC-002 ("never sudo") stays true of the harness's Python as written. Keeping that separation is the point of this
design.

The script cannot read the config, so it acts on `L4_SELF_PROVISION` alone:
- `true` acts;
- `auto` acts on a persistent runner and not on a disposable one, exactly as `resolve_self_provision` does;
- any other value, unset included, prints one `SKIP` line.

The generated GitHub job always sets the variable (D1).

Steps:

1. Facts: the runner environment, the image, whether uv and bwrap are present, the sysctl value. No `sudo` call.
2. uv, pinned at the harness's uv version, with `UV_NO_MODIFY_PATH=1`, into `~/.local/bin`. It is skipped when present.
3. bwrap in user space, `$L4_HOME/bwrap/usr/bin/bwrap`, linked from `~/.local/bin/bwrap`:
   - That binary exists and passes the self-test: `already present`, no download.
   - It does not exist, and another bwrap on PATH passes: nothing is installed.
   - It does not exist: `apt-get download bubblewrap` into a temporary directory, then `dpkg -x`. With no `apt-get` or
     `dpkg`, it reports `manual` and continues.
   - It exists but fails (a cached binary on a kernel that blocks user namespaces): no download; on to the root step.
   - A link to a failing binary is removed, so it cannot shadow a working system bwrap.
4. The root step (D3).
5. On GitHub, append `~/.local/bin` to `$GITHUB_PATH`.

Exit 0 except when uv cannot be installed (exit 2). A bwrap that still fails is not this script's failure: doctor's
SANDBOX checks fail the job with their own hint, as today.

### D3. The root step: one sysctl, disposable runners only

The step runs when all of these hold:
- the runner is disposable (`RUNNER_ENVIRONMENT=github-hosted` or `CI_DISPOSABLE_ENVIRONMENT=true`);
- `sudo -n true` succeeds, or the user is root;
- `L4_PROVISION_ROOT` is not `0`;
- the user-space bwrap fails its self-test;
- `kernel.apparmor_restrict_unprivileged_userns` is `1`.

The conditions are checked in that order, and `sudo -n true` is the last check. So a persistent runner, an opt-out or a
working bwrap never runs `sudo` at all. It then runs `sudo -n sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`
and tests again. It never runs
`apt-get install`: on 24.04 the apt-installed bwrap fails exactly like the user-space one [V].

Cost, stated plainly: the setting lowers a kernel hardening measure for the whole VM for the rest of the job. That is
acceptable only because a hosted VM is single-tenant and destroyed after the job. On a persistent runner the script
prints the command and never runs it.

Rejected alternatives:
- `sandbox.mode: none` on hosted runners. The agent would see the job's secrets, the forge token included (L4-SEC-005).
- Pinning `runs-on: ubuntu-22.04`. That image is deprecated (D).
- Loading the `bwrap-userns-restrict` AppArmor profile instead of the sysctl. It is narrower, but it also needs root and
  attaches to `/usr/bin/bwrap` only. It was not tested [U], and it remains a later option.

### D4. The hosted tool cache

The GitHub template has two cache steps. Both are pinned by commit, like the template's other actions:
`actions/cache/restore` and `actions/cache/save` v6.1.0, `55cc8345863c7cc4c66a329aec7e433d2d1c52a9`.
- The restore runs before `l4-setup`.
- The save runs after doctor, only when every earlier step succeeded, the restore missed, and the job is on the base
  branch.

The cached paths are:
- `~/.local/bin`;
- `$L4_HOME` (`~/.local/share/l4`, which holds Node, the npm prefix with codex and opencode, and bwrap);
- `~/.local/share/claude`;
- `~/.local/share/uv` (uv-managed Pythons);
- `$L4_CACHE` (`~/.cache/l4`);
- uv's cache (`~/.cache/uv`).

The key is `l4-tools-<runner.os>-<runner.arch>-<ImageOS>-<hash of the vendored catalog.py and l4-setup.sh>`. `ImageOS` is
a runner variable, not part of the `env` context, so a step writes it to an output first. No path of
`sandbox.credential_paths` is cached. That leaves out `~/.claude`, `~/.codex` and `~/.kiro`, and also
`~/.local/share/opencode` and `~/.local/share/kiro-cli`. The spike's cache held those last two; this design drops them. Kiro's installer has no version argument, so the cached kiro-cli is
whichever version landed first. The doctor line records it.

### D5. Credentials from the environment

The variable of a profile:
- claude-code: `CLAUDE_CODE_OAUTH_TOKEN` (`auth: subscription`), or `ANTHROPIC_API_KEY` (`auth: api_key`).
- codex: `CODEX_API_KEY`, for `auth: api_key` only.
  - A subscription profile keeps its ChatGPT file login and is never given an API key.
  - `codex login --with-api-key` is never run, because it is a login command (L4-PRV-007).
- kiro-cli: `KIRO_API_KEY`, for `auth: subscription` or `api_key`. It is the headless form of the Kiro login (Pro tier
  and up).

**Probe.** With the variable set:
- the auth step passes without a status command (`auth_method: env`);
- the hello step proves that the credential works;
- the variable is in that profile's probe environment only, which is a child's process environment, never argv.

With the variable unset:
- an `api_key` profile fails auth with `<VARIABLE> is not set`;
- a subscription profile runs today's file-login check, and a failure adds `(or set <VARIABLE>)`.

**Agent sandbox: never `--setenv`.** `build_agent_env` gives bwrap's child no credential, because a `--setenv` value is
in bwrap's argv, which any local user can read through /proc. Instead:
1. The adapter writes the value to a new 0600 file in the step's private directory.
2. It prefixes the command with a loader:
   `/bin/sh -c 'v=$(cat -- "$1") || exit 97; rm -f -- "$1"; export NAME="$v"; shift; exec "$@"'`.
3. The value then reaches only the agent's own process environment, which only the same user can read. The file is
   gone before the agent starts.

This is how `opencode_provider` already delivers a provider key. It is [V] for claude-code (run 38156758955). The value
is redacted like the other `DEFAULT_REDACT_ENV` names, and PRV-001 names a missing variable.

Rejected: `--setenv`. The text of this change said so until 2026-10-11, which contradicted the sandbox's own invariant.

Codex and Kiro with a key stay unproven until a hosted run with `CODEX_API_KEY` and `KIRO_API_KEY` passes.

### D6. Pin the harness's Python

The shim runs `uv run --python <pin> ...`, with the pin taken from the vendored harness.
- The pin is 3.12: the version that CI's checks and `prereqs.sh` PRQ-06 install.
- The reference runner's harness has drifted to 3.13.16 [V]. With the pin it goes back to the 3.12 that PRQ-06 already
  installed.
- A hosted image with a too-old system Python gets a uv-managed 3.12, not whatever uv finds newest.
- A persistent runner with no 3.12 downloads one on the first run, which needs the network.

### D7. Pipeline secrets live in a GitHub Environment

`ci.github_environment` (default `l4`; null turns it off) puts `environment: <name>` on the generated GitHub job, hosted
or self-hosted.
- The forge token and the agent credentials then become secrets of that environment.
- A deployment branch policy can limit them to the base branch and the unit-branch prefix.
- Repository secrets still resolve, so nothing breaks while a repository moves its secrets.
- GitHub creates a missing environment on the first run. Every run is recorded as a deployment of that environment.
- A GitHub secret reaches a job only when its `env` names it. Unlike GitLab, where CI variables are environment
  variables of every job, the template must name each one. It maps exactly the forge token and the credential variable
  of each profile that a role chain uses (SCN-PRV-74). An unset secret maps to an empty value, which the harness treats
  as unset.

The harness repository's own pipelines follow the same rule, with the environments `hosted-agents` and `publication`
[V].

## SPEC amendments required by this change

The text below is proposed. SPEC.md gets only the delivery-table row and the fact update until this change is approved.

1. §1, runtime prerequisites, and L4-DOC-002: add "The separate pre-shim script `.l4/bin/l4-setup` (L4-PRV-020..022) may
   run exactly one root command, the AppArmor user-namespace sysctl. It does so on a disposable runner only, with
   passwordless sudo and no `L4_PROVISION_ROOT=0`. `doctor --fix` itself never escalates."
2. §3.2, the `ci.self_provision` comment: "`L4_SELF_PROVISION` (true|false|auto) overrides this key when set
   (L4-PRV-019)."
3. L4-DOC-002, first bullet: the GitHub facts change from [D] to [V] (`RUNNER_ENVIRONMENT=github-hosted`, run
   38144352581).
4. The generated-CI sentence of L4-DOC-002 gains: "On GitHub, the job runs `.l4/bin/l4-setup`, then `l4 doctor --ci
   --fix`, when `L4_SELF_PROVISION` (the repository variable, else the rendered config value) resolves true, between a
   tool-cache restore and save (L4-PRV-023)."
5. The adapter auth rows of §8 (claude-code, codex, kiro-cli): the credential variable reaches its own profile only. It
   goes into that profile's probe environment, and into its agent process through a 0600 file and a loader, never
   bwrap's argv (L4-PRV-024).
6. §15: PRV-001 names the missing variable.
7. §21: add the row for change 14 `hosted-runner-setup`.
8. §3.2 `ci:` gains `github_environment: l4` (L4-PRV-027): "the GitHub Environment whose secrets the generated job
   reads; null: none"; the GitHub part of §14 says the forge token and agent credentials belong there.

## Risks

- **The sysctl widens the kernel's attack surface for the job.** It is mitigated by running only on single-tenant
  throwaway VMs, by the opt-out, and by being logged.
- **GitHub may change the image.** A bwrap profile could appear, or the default could change. The self-test decides at
  every run, so the script adapts and records the facts.
- **Free models are slow and change.** The hello took 4.5 s cold and 43 s warm on the same image [V]. Probe timeouts and
  free-model choices are config, not code.
- **The agent's own tools see its credential.** A variable in the agent's process environment is inherited by the
  commands it runs, such as the gate prefix running tests it wrote. Today a file login is just as visible to them: the
  adapter's credential paths are bound into its sandbox. This change does not widen what the agent's process tree can
  read; it narrows what other local users can read (no argv). Redaction and the secret scan still guard the diff and the
  logs.
- **Deployment noise.** Each run of a job with `environment:` is a deployment record, about one every 30 minutes with the
  schedule. `ci.github_environment: null` turns it off.
- **Cache poisoning across branches.** Caches are scoped per branch by GitHub, and the key includes the pins. The cache
  holds binaries the job runs, so it is saved only from the base branch's job.
