## Why

The `l4` job cannot start on a runner that nobody prepared. Examples are a GitHub-hosted `ubuntu-24.04` VM and any
other throwaway VM. `ubuntu-24.04` is what the generated GitHub workflow targets when `ci.runner_tags` is empty. Three
things fail [V, docs/spikes/06-hosted-runner-setup.md]:

- The shim `.l4/bin/l4` exits 3 because no hosted image has uv.
- `ci.self_provision: auto` resolves false on a hosted runner, so the doctor installs no agent CLI.
- The sandbox cannot start. bwrap is missing, and on Ubuntu 24.04 AppArmor refuses unprivileged user namespaces even to
  an apt-installed bwrap.

The spike ran on real GitHub-hosted runners (run 38144352581). It showed that one flag and one setup step take a bare
image to a working state in under two minutes cold:

- the four agent CLIs installed at the pinned versions;
- the harness's own bwrap sandbox working;
- an OpenCode free-model call succeeding inside that sandbox.

With a tool cache, the install step takes 7 s. The only root step needed is one kernel setting, and only on Ubuntu 24.04.
Ubuntu 22.04 needs none. This change makes that the supported path, behind a flag that a repository or organisation
variable can switch without a commit.

## What Changes

- **Environment override.** `L4_SELF_PROVISION` (`true`, `false` or `auto`, case-insensitive) overrides
  `ci.self_provision` when set; any other value is ignored with a warning. The GitHub template passes the repository
  variable `vars.L4_SELF_PROVISION`. When that variable is unset, the template falls back to the value rendered from the
  config.
- **A setup step that runs before the first `l4` command.** `l4 init` and `l4 upgrade` write a new vendored shell script,
  `.l4/bin/l4-setup`, run by the generated CI job when provisioning resolves true. Its steps, in order:
  1. Install pinned uv user-locally when missing.
  2. Install bwrap in user space (`apt-get download` + `dpkg -x` into `$L4_HOME/bwrap`, Debian and Ubuntu), with an
     `already present` check.
  3. On a disposable runner only, with passwordless sudo and no opt-out, run exactly one root command:
     `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. It runs only when the user-space bwrap fails on its uid
     map and the setting is 1. Then bwrap is tested again.
  4. Make `~/.local/bin` visible to the following steps (`$GITHUB_PATH` on GitHub).

  With the flag off it prints one `SKIP` line and changes nothing. The agent CLIs are still installed by `l4 doctor --ci
  --fix`, unchanged; no root step ever enters the doctor.
- **GitHub template.** It restores a tool cache before `l4-setup`, keyed on the runner OS, the image and the pinned
  versions, and saves it after doctor. The order becomes: `l4-setup`, `doctor --ci --fix`, `plan --sweep`, `run`.
- **Credentials from the environment for Claude Code, Codex and Kiro.**
  - The probe and the agent process receive exactly the credential variable of the step's own profile:
    - claude-code: `CLAUDE_CODE_OAUTH_TOKEN` (subscription) or `ANTHROPIC_API_KEY` (api_key);
    - codex: `CODEX_API_KEY` (api_key);
    - kiro-cli: `KIRO_API_KEY`.
  - Into the sandbox the value travels through a 0600 file and a loader, never bwrap's argv. Claude Code works that way
    on both hosted images [V, run 38156758955].
  - The value is redacted from every output.
  - Codex `auth: api_key` stops being refused by the probe.
  - A missing credential is reported by its variable name.
- **Pipeline secrets in a GitHub Environment.** The new key `ci.github_environment` (default `l4`) puts
  `environment: <name>` on the generated GitHub job. The forge token and agent credentials are then environment secrets.
  This repository's own pipelines already use the environments `hosted-agents` and `publication`, and it has no
  repository secrets left.
- **Pinned harness Python.** On a hosted image whose Python is older than 3.11, uv chose 3.14.8. The shim now pins the
  harness's Python, so hosted runs use the version the reference runner and the test suite use.
- **Documentation.** The quickstart gets a "GitHub-hosted runner" path, and the runner README gets the root-step policy.
- Requires SPEC amendments, listed in design.md. The main one is a carve-out next to L4-DOC-002: the doctor stays
  root-free, and the separate `l4-setup` may run its one root command on a disposable runner.

## Capabilities

### New Capabilities

- `hosted-runner-setup`: the provisioning override, the pre-shim setup step, user-space bwrap, the one root step and
  where it may run, the hosted tool cache, credentials from the environment, and the pinned harness Python.

### Modified Capabilities

None as an OpenSpec delta. `runner-provisioning` (change 12) is not archived. This change adds requirements L4-PRV-019 to
L4-PRV-026 next to it and names the SPEC lines it amends in design.md.

## Impact

- Code:
  - `src/l4/provision/runner.py`: the override.
  - `src/l4/config/schema.py`: `ci.github_environment`.
  - `src/l4/ci/render.py`, `src/l4/ci/github.py` and `src/l4/ci/templates/`: `l4-setup`, the GitHub template and the
    shim's Python pin.
  - `src/l4/init/init.py` and `src/l4/init/upgrade.py`: write `l4-setup`.
  - `src/l4/availability/probes.py` and `src/l4/agents/{claude_code,codex,kiro_cli}.py`: credential variables.
  - `src/l4/doctor/checks_provision.py`: readiness lines that name variables.
- Docs: `docs/SPEC.md` (the amendments and the delivery-table row 14), `docs/quickstart.md`, `docs/runner/README.md`.
- Evidence and prototype: `docs/spikes/06-hosted-runner-setup.md`, `scripts/runner/hosted-setup.sh` (replaced
  by `src/l4/ci/templates/l4-setup.sh`), `.github/workflows/spike-hosted-setup.yml`, `scripts/runner/spike-hosted/`.
- Unchanged:
  - GitLab shell runners: never disposable, so no root step ever runs there.
  - GitLab Docker executors: out of scope, because bwrap cannot create a user namespace in an unprivileged container
    [V, local rehearsal].
  - A full `l4 run` against a GitHub forge: change 13 `live-validation`.
