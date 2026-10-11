## Context

Evidence for everything labelled [V] is `docs/spikes/06-hosted-runner-setup.md`: GitHub Actions run 38144352581, with jobs
114484478622 (`ubuntu-24.04`, cold), 114484478868 (`ubuntu-22.04`, cold) and 114484850081 (`ubuntu-24.04`, warm). The
prototype is `scripts/runner/hosted-setup.sh` on branch `spike/hosted-agent-setup`.

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
- [V] On 22.04, ENV-001 reported Python 3.14.8: uv provisioned a newer interpreter for the vendored harness.
- [I, code] `availability/probes.py:75` refuses `api_key` profiles. The probe and sandbox environments forward no
  credential variable, and no probe line names a missing variable.
- [D] GitHub deprecates the ubuntu-22.04 image with brownouts from 2026-09-17 and removes it on 2027-04-17.

## Goals

- One flag turns a bare hosted runner into a working L4 runner. Off means nothing changes.
- The flag can be switched without a commit (repository or organisation variable) and from the config.
- No root on any persistent runner, ever. On a disposable runner, at most one root command, only when it is needed and
  only with an opt-out.
- A cached job pays seconds, not minutes.
- Claude Code, Codex and Kiro can authenticate from secrets alone, with no login command.

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

Steps:

1. Facts: the runner environment, the image, sudo, whether uv and bwrap are present, the sysctl value.
2. uv, pinned at the harness's uv version, with `UV_NO_MODIFY_PATH=1`, into `~/.local/bin`. It is skipped when present.
3. bwrap in user space: `apt-get download bubblewrap` into a temporary directory, then `dpkg -x` into `$L4_HOME/bwrap`,
   linked from `~/.local/bin/bwrap`.
   - Skipped when that binary exists and passes the self-test.
   - With no `apt-get` or `dpkg`, it reports `manual` and continues.
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

It then runs `sudo -n sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` and tests again. It never runs
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

The GitHub template has two cache steps:
- `actions/cache/restore` before `l4-setup`;
- `actions/cache/save` after doctor, on success only.

The cached paths are:
- `~/.local/bin`;
- `$L4_HOME` (`~/.local/share/l4`, which holds Node, the npm prefix and bwrap);
- `$L4_CACHE` (`~/.cache/l4`);
- `~/.local/share/claude`, `~/.local/share/kiro-cli` and `~/.local/share/opencode`;
- uv's cache.

The key is `l4-tools-<runner.os>-<ImageOS>-<hash of the vendored pins>`. Credentials are never in these paths:
`~/.claude`, `~/.codex` and `~/.kiro` are left out. Kiro's installer has no version argument, so the cached kiro-cli is
whichever version landed first. The doctor line records it.

### D5. Credentials from the environment

Per adapter, the credential variable is:
- claude-code: `CLAUDE_CODE_OAUTH_TOKEN` (`auth: subscription`), or `ANTHROPIC_API_KEY` (`auth: api_key`, with `--bare`);
- codex: `CODEX_API_KEY`, inline on `codex exec`. `codex login --with-api-key` is never run, because it is a login
  command (L4-PRV-007);
- kiro-cli: `KIRO_API_KEY` (Pro tier and up).

Only the step's own profile variable enters its probe and its agent sandbox (`--setenv`). It is redacted like the other
`DEFAULT_REDACT_ENV` names. A missing variable is reported as `<profile>: <VARIABLE> is not set`, in the probe line and
in PRV-001.

This is the least proven part. It is labelled unproven until a hosted run with the three secrets passes D'.

### D6. Pin the harness's Python

The shim runs `uv run --python <pin> ...`, with the pin taken from the vendored harness (3.12, the reference runner's
version). A hosted image with a too-old system Python then gets a uv-managed 3.12, not whatever uv finds newest.

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
5. The adapter auth rows of §8 (claude-code, codex, kiro-cli): the credential variable reaches the probe and the agent
   sandbox of its own profile only (L4-PRV-024).
6. §15: PRV-001 names the missing variable.
7. §21: add the row for change 14 `hosted-runner-setup`.

## Risks

- **The sysctl widens the kernel's attack surface for the job.** It is mitigated by running only on single-tenant
  throwaway VMs, by the opt-out, and by being logged.
- **GitHub may change the image.** A bwrap profile could appear, or the default could change. The self-test decides at
  every run, so the script adapts and records the facts.
- **Free models are slow and change.** The hello took 4.5 s cold and 43 s warm on the same image [V]. Probe timeouts and
  free-model choices are config, not code.
- **Cache poisoning across branches.** Caches are scoped per branch by GitHub, and the key includes the pins. The cache
  holds binaries the job runs, so it is saved only from the base branch's job.
