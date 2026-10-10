## Why

The product goal is that a person runs one script or a couple of commands and the harness is usable in an existing project. Today the SPEC
(section 1) says runtime prerequisites are "checked by doctor, never silently installed in CI", doctor `--fix` has no entry for any ENV check, and
section 16.3 says agent CLIs are "expected pre-installed". On the reference runner `l4-runner` (shell executor, linux/amd64, a black box with
no SSH) that means a human must install uv, Node >= 20.19, OpenSpec and three or four agent CLIs by hand before the first job can pass,
and a first inventory job already died in "prepare environment" because of the runner user's `~/.bash_logout` (`clear_console`) before any script ran.
This change makes the shell runner self-sufficient where that is safe (user-local installs, no root, no authentication) and tells the human exactly what is
left (sudo commands, logins, masked variables).

## What Changes

- Add `install.sh` at the harness repository root: a pinned-SHA one-liner that installs uv user-locally when missing and runs
  `uvx --from git+<url>@<sha> l4 <args>` (for example `init --ci gitlab`). Footprint in the target repo stays exactly L4-INS-002.
- Add `l4 doctor --fix` provisioning: uv to `~/.local/bin`, a pinned Node tarball under `$L4_HOME/node` when Node is missing or older than 20.19,
  OpenSpec 1.14.0 into `$L4_CACHE/tools/openspec-<version>`, agent CLIs through their official installers (claude, opencode, kiro-cli) or an npm prefix
  (`@openai/codex`). Never root: root-only prerequisites (bubblewrap) are printed as the exact `sudo` command.
- Never authenticate: print per-adapter human steps (`claude setup-token` into masked `CLAUDE_CODE_OAUTH_TOKEN`, OpenRouter key, Codex device login on the VM, `kiro-cli login`)
  and report each adapter as `ready`, `installed-not-authenticated` or `missing`, without e-mail or token in any output.
- Add config key `ci.self_provision` (`auto` default, `true`, `false`); the generated CI file runs `l4 doctor --ci --fix` first when it resolves true (GitLab default).
- Document the `.bash_logout` / `clear_console` failure signature and fix in `docs/runner-setup.md`, and print a notice from `l4 init` for GitLab targets.
- Idempotence, atomic installs, offline behaviour (exit 3 with the manual command), checksum verification, clean installer environment, one tool search path,
  a provisioning lock and `--fix --dry-run`.
- Requires SPEC amendments (listed in design.md "SPEC amendments") because this change deliberately deviates from section 1, section 15 and section 16.3.

## Capabilities

### New Capabilities

- `runner-provisioning`: one-command install, user-local tool provisioning by `l4 doctor --fix`, adapter readiness and human authentication steps, CI self-provisioning,
  runner failure documentation, idempotence and offline behaviour.

### Modified Capabilities

None. (The doctor framework, config schema and CI templates belong to changes 1 and 9; this change adds checks, one config key and a render rule through their extension points, see Impact.)

## Impact

- Owned paths: `install.sh`, `src/l4/provision/runner.py`, `src/l4/provision/catalog.py`, `src/l4/provision/readiness.py` (the layout names `provision/runner.py`; the
  two extra modules stay inside `src/l4/provision/`), `src/l4/doctor/checks_provision.py`, `docs/runner-setup.md`, `tests/unit/provision/`, `tests/e2e/provision/`.
- Depends on `bootstrap-core` (change 1): doctor framework (`register`, `attach_fix`, `Fix`, `FixScope`), config schema (key `ci.self_provision`, defined there in its task 1.4), `cache_root`, exit codes, redaction.
- Consumed by `forge-and-ci` (change 9): its template renderer calls `doctor_command(cfg, platform)` (its task 1.15) and `l4 init --ci gitlab` prints `GITLAB_RUNNER_NOTICE` (its task 1.27); this change owns the contract tests
  (`tests/unit/provision/test_ci_render.py`) and the text of the notice.
- Depends on `agent-factory` (change 5) for profiles, `min_version` and the `binary`/`auth` probe steps (L4-AVL-001); M1 uses a minimal local implementation of the same probes.
- Feeds `sandbox-security` (change 11): bubblewrap root hint consumed by `SANDBOX-001`.
- Consumes the spike `22-userlocal-provisioning` (change `spikes`) for the [U] installer facts.
- No change to any file inside the target repository beyond the L4-INS-002 footprint; tools land in `~/.local/bin`, `$L4_HOME` (default `~/.local/share/l4`) and `$L4_CACHE` (default `~/.cache/l4`).
