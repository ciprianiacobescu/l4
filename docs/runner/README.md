# Runner prerequisites (shell-executor GitLab runner)

How to prepare a GitLab **shell-executor** runner host for the L4 harness, reproducibly. Every statement below is
backed by a script in [`scripts/runner/`](../../scripts/runner) and an evidence file in this folder; nothing here is
assumed. The reference host is `l4-runner` (GitLab runner #12, runner name `l4-runner`), first prepared on
2026-10-03.

## TL;DR

```bash
# from a workstation that can reach the host (here: through the Mintkey SSH bastion)
scripts/runner/mk-ssh.sh --script scripts/runner/inspect.sh                 # 1. read-only inventory
scripts/runner/mk-ssh.sh --script scripts/runner/prereqs.sh -- --check      # 2. what is missing (changes nothing)
scripts/runner/mk-ssh.sh --script scripts/runner/prereqs.sh -- --apply      # 3. fix/install (idempotent)
# 4. prove it from a real CI job: push a branch whose .gitlab-ci.yml runs scripts/runner/ci-probe.sh with tags: [agentic]
# 5. human-only: agent logins (see "Authentication"); if they were made as the SSH admin user, move them:
scripts/runner/mk-ssh.sh --script scripts/runner/prereqs.sh -- --apply --adopt-logins-from <admin-user>
scripts/runner/mk-ssh.sh --script scripts/runner/hello.sh                   # 6. "say hello" probe per agent CLI
```

On the host itself, without Mintkey: `bash inspect.sh`, `bash prereqs.sh --check`, `bash prereqs.sh --apply` as a
user with passwordless sudo.

## Scripts

| Script | Changes anything? | Purpose |
|---|---|---|
| [`mk-ssh.sh`](../../scripts/runner/mk-ssh.sh) | no | Runs a command or pipes a script to a host through the Mintkey SSH bastion. Requests a 10-minute JWT for the service (default `ssh-runner`), logs in as the agent id (the JWT `sub`) with the JWT as password. The JWT stays in the process environment (`sshpass -e`); it is never printed or stored. |
| [`inspect.sh`](../../scripts/runner/inspect.sh) | no | Inventory: OS, CPU/RAM/disk, user namespaces, gitlab-runner service and config (no tokens), login-shell health of the runner user, tools on the runner user's login PATH, credential **presence** (never contents), egress, local services. |
| [`prereqs.sh`](../../scripts/runner/prereqs.sh) | `--apply` only | The prerequisites, as steps `PRQ-01..21`, each with a check, an apply and a re-check. Pinned versions at the top (env-overridable). System changes use sudo; tools are installed **as the runner user** into its home. Exit 0 = all satisfied, 1 = something missing (`--check`), 2 = an apply failed. |
| [`hello.sh`](../../scripts/runner/hello.sh) | no (spends a few tokens) | The `hello` availability probe (L4-AVL-001) per agent CLI, run as the runner user in a fresh login shell from an empty directory: reply must be exactly `L4-OK`. `PROBES="claude:haiku codex:default opencode:opencode/big-pickle"` by default. |
| [`sandbox-probe.sh`](../../scripts/runner/sandbox-probe.sh) | no (spends a few tokens) | Runs each agent CLI **inside bubblewrap** as the runner user on a scratch uv project: `uv sync` outside, then the agent edits code and runs `.venv/bin/python -m pytest` inside; checks edit, tests and that no test file changed. `SANDBOX=none` runs the same task unsandboxed for comparison. `SANDBOX=m0` builds exactly the argv of `l4.sandbox.bwrap.BwrapSandbox` for an agent (worktree layout, other logins hidden, `.git` read-only, `--clearenv`), runs the isolation canaries inside it, codex as the implementer and claude as the tool-less judge; `tests/unit/sandbox/test_probe_parity.py` keeps the bash and Python argv identical. |
| [`ci-probe.sh`](../../scripts/runner/ci-probe.sh) | no | The same inventory from *inside* a CI job, i.e. exactly what a job sees (login PATH, user, egress). |
| [`mk-azdo-agent.sh`](../../scripts/runner/mk-azdo-agent.sh) | `--apply`/`--remove` | From a workstation with `az` logged in: the Azure DevOps pool `agentic` and its project queue (pipelines need a one-time authorization), a one-day PAT of scope Agent Pools (read & manage) used once and revoked on exit, then `azdo-agent.sh` on the host through `mk-ssh.sh` with the PAT inside the piped script. `--check` is read-only; `--smoke` runs one job on the pool without touching a repository. See "Azure Pipelines agent". |
| [`azdo-agent.sh`](../../scripts/runner/azdo-agent.sh) | `--apply`/`--remove` | On the host: the user `azdo-agent` (own group, home 750, not in `docker`), the agent package, its dependencies, `config.sh --unattended` with the token from `VSTS_AGENT_INPUT_TOKEN`, the systemd service. `--apply` refuses to register while that user can read any of gitlab-runner's agent logins. |

## Steps (`prereqs.sh`)

| ID | Requirement | Why | Apply (what `--apply` does) |
|---|---|---|---|
| PRQ-01 | `bash --login` as the runner user exits 0 | The shell executor starts every job with a login shell. Ubuntu's default `~/.bash_logout` runs `clear_console -q` when `SHLVL=1`; with no console it fails and GitLab reports `ERROR: Job failed: prepare environment: exit status 1` right after `Running on <host>...`, before any script runs (seen: dummy-agentic job 5415). No CI file can work around it. | `mv ~gitlab-runner/.bash_logout ~gitlab-runner/.bash_logout.disabled-by-l4` |
| PRQ-02 | apt packages `bubblewrap git curl jq ca-certificates xz-utils unzip` | bubblewrap is the L4 sandbox (decision Q6); the rest are used by the installers and the harness. The only root-level installs. | `apt-get install -y …` |
| PRQ-03 | git ≥ 2.34 | Worktrees, `push --atomic`, `commit --trailer` (2.32+). 2.34 is Ubuntu 22.04's git, so no PPA is needed. | none (report only) |
| PRQ-04 | `bwrap --unshare-all … true` works as the runner user | Unprivileged user namespaces must be allowed (`kernel.unprivileged_userns_clone=1`, AppArmor userns restriction off). | none (report only — a sysctl change is a host-policy decision) |
| PRQ-05 | uv `0.12.22` in `~/.local/bin` | Runs the harness (`uvx --from git+…@<sha> l4`). Ubuntu's `~/.profile` adds `~/.local/bin` to PATH for login shells, i.e. for jobs. | official installer `https://astral.sh/uv/0.12.22/install.sh` with `UV_NO_MODIFY_PATH=1` |
| PRQ-06 | a uv-managed CPython 3.12 | Ubuntu 22.04 ships 3.10; the harness needs ≥ 3.11. | `uv python install 3.12` (run from `~`: uv reads `uv.toml` from the cwd) |
| PRQ-07 | Node ≥ 20.19 | OpenSpec 1.14.0's engines requirement; npm-distributed CLIs. | only if missing/old: pinned Node 22 tarball under `~/.local/share/l4/node` |
| PRQ-08 | OpenSpec `1.14.0` in the harness-owned prefix `~/.local/share/l4/npm` | The harness never runs `npx` inside a target repo (a planted `node_modules/.bin/openspec` would execute — reproduced during design). | `npm install --prefix ~/.local/share/l4/npm @fission-ai/openspec@1.14.0` |
| PRQ-09 | Claude Code `2.1.288` | Implementer / judge adapter `claude-code`. | official installer `https://claude.ai/install.sh` with the version argument |
| PRQ-10 | Codex CLI `0.160.0` | Adapter `codex`; also its zero-cost quota probe (`codex app-server`). | `npm install` into the harness prefix, linked to `~/.local/bin/codex` |
| PRQ-11 | OpenCode ≥ `1.18.34` | Adapter `opencode`. An existing system install is kept when new enough. | `npm install opencode-ai@1.18.34` into the harness prefix, linked |
| PRQ-12 | Kiro CLI at the catalog pin (`2.32.0`) | Adapter `kiro-cli`. The versioned archive, never `latest`; the installed version must equal the pin. | download `https://prod.download.cli.kiro.dev/stable/<pin>/kirocli-<arch>-linux.zip`, check it with `sha256sum -c`, `install -m 755` the three binaries into `~/.local/bin`; no `kiro-cli update`, no installer script |
| PRQ-13 | (optional) Serena `1.7.0`, warmed | Memory MCP server (M1.5). The first MCP `initialize` must not time out. | `uv tool install -p 3.13 serena-agent==1.7.0` (`--with-serena`), then `uvx -p 3.13 --from pyright==<the pin of the installed Serena> pyright --version` to warm Pyright's uv environment and npm package |
| PRQ-14 | (optional) Playwright Chromium `1.63.0` in `~/.cache/l4/shared/ms-playwright` | e2e gates (M1.5). That is where the gate sandbox mounts the browser read-only (`$L4_CACHE/shared/ms-playwright`). | `npx playwright@1.63.0 install-deps chromium` (root) + Python `playwright install chromium` with `PLAYWRIGHT_BROWSERS_PATH` set (`--with-playwright`) |
| PRQ-18 | (optional) Laya `0.3.24` + the `typed-decisions` checkpoint | System-One judge (M1.5, L4-FAC-004); whether it runs on the runner is decided by `ci-probe-m15.sh` (M15-G2). | `uv tool install --torch-backend cpu 'laya[serve]==0.3.24'` and a Hugging Face prefetch of `typed-decisions` (`--with-laya`) |
| PRQ-15 | authentication (report only) | Logins are human decisions; the script reports presence only. | none — see below |
| PRQ-16 | capacity (warning) | RAM < 8 GB. | none — see "Open warnings" |
| PRQ-19 | isolation (warning) | runner user in the `docker` group (the L4 sandboxes mask the socket; other jobs and the harness process do not). | none: removing the membership is the maintainer's decision — see "Open warnings" |
| PRQ-20 | (optional) OpenCode 2 at the catalog pin (`2.0.32`), as `opencode2` in its own prefix | Adapter `opencode` for a profile with `options.cli_major: 2` (experimental and not yet checked against a live run, L4-OCV-002, runbook 10.9). v2 migrates the runner user's `opencode.db` in place, so install it only for a runner user that no OpenCode 1 profile shares. `@opencode/cli` also ships a bin named `opencode`, so it never goes into PRQ-11's prefix and only `opencode2` is linked; the installed version must equal the pin and a v1 under this name is refused. | `npm install --prefix ~/.local/share/l4/npm-opencode2 --save-exact @opencode/cli@2.0.32`, then link only `node_modules/.bin/opencode2` as `~/.local/bin/opencode2` (a regular file there is never replaced; `--with-opencode2`) |
| PRQ-21 | no agent CLI updates itself | `DISABLE_AUTOUPDATER` for Claude Code, `app.disableAutoupdates` for Kiro (L4-PRV-044). Runs no agent CLI. | merges `env.DISABLE_AUTOUPDATER` into `~/.claude/settings.json` and `app.disableAutoupdates` into `~/.kiro/settings/cli.json` with `jq`; a file that is not a JSON object is left untouched and the step fails |
| PRQ-22 | (optional) Copilot CLI at the catalog pin (`1.0.102`), warmed | Adapter `copilot-cli` (experimental, in no default chain). The release tarball, never the vendor's installer script; the installed version must equal the pin (a Copilot CLI 2 is refused). | download `https://github.com/github/copilot-cli/releases/download/v<pin>/copilot-<linux\|linuxmusl>-<x64\|arm64>.tar.gz`, check it with `sha256sum -c` (the four Linux digests are in the script's top block), extract only `copilot`, `install -m 755` it into `~/.local/bin`, then run `copilot --version` once with `XDG_CACHE_HOME=~/.local/share/l4/copilot-cache` to extract its package there (`--with-copilot`) |
| PRQ-17 | (opt-in) adopt logins made as another user | Humans often log in as the SSH admin user, but jobs run as the runner user. The credential files are **moved**, not copied: two copies of one OAuth refresh token race on refresh and one stops working (L4-FAC-008). An existing runner-user login is never overwritten. | `--adopt-logins-from <user>`: moves `~/.claude/.credentials.json` and `~/.codex/auth.json`, owner runner user, mode 600 |

## Observed on `l4-runner` (2026-10-03)

| Fact | Value | Evidence |
|---|---|---|
| Host | Ubuntu 22.04.5 LTS, kernel 6.8.0-138, x86_64, 4 vCPU, 3.8 GB RAM + 2 GB swap, 281 GB free | [inspect-2026-10-03-before.txt](inspect-2026-10-03-before.txt) |
| GitLab runner | 19.4.1, systemd service active, one runner `l4-runner` (id 12), executor `shell`, `concurrent = 1`, runs as `gitlab-runner` | same |
| Admin access | user `admin` with passwordless sudo, through the Mintkey service `ssh-runner` | same |
| Before | `.bash_logout` with `clear_console`; no uv, claude, codex, kiro-cli; opencode 1.18.34 (`/usr/local/bin`) configured for a local OpenAI-compatible provider `magnitude`; bubblewrap 0.6.1 already installed and working | [prereqs-2026-10-03-check-before.txt](prereqs-2026-10-03-check-before.txt) |
| Apply | PRQ-01, 05, 06, 08, 09, 10, 12 fixed; first run failed PRQ-06 (uv read `/home/admin/uv.toml` because sudo kept the admin's cwd) → script fixed to `cd ~` → second run all OK | [prereqs-2026-10-03-apply.txt](prereqs-2026-10-03-apply.txt), [prereqs-2026-10-03-apply-2.txt](prereqs-2026-10-03-apply-2.txt) |
| From a real job | pipeline #2525 on `l4/probe-runner` succeeded on `l4-runner`; job PATH starts with `/home/gitlab-runner/.local/bin`; uv 0.12.22, claude 2.1.288, codex-cli 0.160.0, opencode 1.18.34, kiro-cli 2.27.1, bwrap 0.6.1, node 22.23.3, git 2.34.1 | [ci-probe-2026-10-03-pipeline-2525.txt](ci-probe-2026-10-03-pipeline-2525.txt) |
| Logins | maintainer logged in to Claude Code (subscription `pro`) and Codex as `admin`; PRQ-17 moved both to `gitlab-runner`; OpenCode's free models (`opencode/*-free`, `opencode/big-pickle`, 10 models) need no login; Kiro CLI not logged in | [prereqs-2026-10-03-adopt-logins.txt](prereqs-2026-10-03-adopt-logins.txt), [prereqs-2026-10-03-check-after-logins.txt](prereqs-2026-10-03-check-after-logins.txt) |
| Hello probes | as `gitlab-runner`: claude haiku PASS 2.6 s, codex (default model) PASS 5.4 s, opencode `opencode/big-pickle` PASS 6.1 s | [hello-2026-10-03.txt](hello-2026-10-03.txt) |
| Nested sandbox | inside `bwrap --ro-bind / / --tmpfs /tmp --unshare-pid --unshare-ipc --share-net` with only the worktree and the CLI's own state dirs writable: claude (haiku) PASS 10.4 s, codex PASS 31.0 s (its own sandbox nested inside bwrap), opencode `big-pickle` PASS 18.4 s; no test file changed. Gap for M2: `/` is readable, so the profile must also hide the *other* CLIs' credential dirs (tmpfs over them) | [sandbox-probe-2026-10-03.txt](sandbox-probe-2026-10-03.txt) |
| Jev (TypeSafe System-One) | key stored only in Mintkey (`typesafe-jev-api-key`), copied unprinted into the masked CI variable `TYPESAFE_API_KEY` (`scripts/forge/gitlab_ci_var_from_mintkey.py`). Smoke test `scripts/runner/ci-jev-smoke.py` (noul + choice + score in one request): from the Mac HTTP 200 in 275 ms, from a CI job on the runner (pipeline 2612) HTTP 200 in 272 ms, model `jev-1.13.0`, 523 in / 77 out tokens. Identical requests drift slightly (noul 0.21 vs 0.25, score 2.59 vs 2.71) — not bit-for-bit deterministic | [ci-jev-smoke-2026-10-04-pipeline-2612.txt](ci-jev-smoke-2026-10-04-pipeline-2612.txt) |
| Egress | openrouter.ai 200, npm 200, PyPI 200, GitHub 200, api.anthropic.com / api.openai.com reachable (404/421 on `/`), gitlab-host GitLab 302 | same |

## M1.5 probe (M15-G2, 2026-10-04): Playwright, Serena and Laya in the harness sandbox

One job, [`ci-probe-m15.sh`](../../scripts/runner/ci-probe-m15.sh), pipeline 2549 on the throwaway branch `probe/m15`
(deleted afterwards); the log is [ci-probe-m15-2026-10-04-pipeline-2549.txt](ci-probe-m15-2026-10-04-pipeline-2549.txt).
`prereqs.sh --apply --with-serena --with-playwright --with-laya` ran first ([apply log](prereqs-2026-10-04-apply-m15.txt),
[check after](prereqs-2026-10-04-check-m15-after.txt)). The runner reported more RAM that day than the 3.8 GB above, and not one figure: 7107 MB total in the PRQ-16 line of
the [check after](prereqs-2026-10-04-check-m15-after.txt), 5254 and 5154 MB in the probe job's `free -m`
([pipeline 2549](ci-probe-m15-2026-10-04-pipeline-2549.txt)). The 9.1 GB upper figure is not in any of these logs.
Two OpenCode sessions of another user (1.1 GB) were resident during the probe, which does not change any decision below.

| Part | Result |
|---|---|
| (a) pytest-playwright in one gate spawn (`--unshare-net`, the argv `BwrapSandbox` builds for a gate) | PASS without `--tmpfs /dev/shm` (2.8 s, peak tree RSS 541 MB) and with it (1.4 s, 645 MB). Loopback works inside the unshared namespace, so one spawn can hold the server and the tests (D4). |
| (b) `serena start-mcp-server --context codex ...` in the agent argv | MCP `initialize` in 1.4 s; 23 tools, 6 memory tools; `get_symbols_overview` (starts Pyright via `uvx`) 1.9 s; peak tree RSS 294 MB. **Two findings:** `uvx` fails under the read-only HOME unless `UV_TOOL_DIR` points at a writable directory, and a generated `serena_config.yml` must carry `projects: []` next to `base_modes: [editing]` (without it Serena exits with `SerenaConfigError`). Line 19 (`serena_env`) sets both. |
| (c) `laya-serve`, `typed-decisions`, 2 threads | ready in 5.5 s (14.1 s on a cold file cache); p50 of 5 `noul` calls 864 ms; 5 byte-identical answers (`be885303ea39`); peak tree RSS **2.48 GB** (2.88 GB cold). Tokenizer: a state of 450 approx-tokens (chars / 4) is 386 Laya tokens for prose, 613 for JSON and 683 for code; the largest approx-token count within the 463-token window is 540 (prose), 340 (JSON), 300 (code). |
| (d) TCP from the runner to `192.0.2.10` | port 8000 connect ok; 8765 and 22 refused (the host answers). Whether the listener on 8000 is `laya-serve` is not known; the probe only connects. |
| (e) `cache_root` in a job | `L4_CACHE` and `XDG_CACHE_HOME` unset, so `~/.cache/l4`; the gate's read-only `playwright` mount `~/.cache/l4/shared/ms-playwright` is the directory PRQ-14 installs into. |

Decisions:

* **P1: no change.** Chromium runs in the gate sandbox without `--tmpfs /dev/shm`, so `bwrap.base_flags`, `sandbox-probe.sh`
  and the parity test stay as they are (line 37 is dropped).
* **P2: Laya runs on the runner (`engine: laya-local`).** Maintainer override of 2026-10-04: the VM balloons up to 10 GB,
  so the 1.2 GB bar is dropped (the probe's 2.48 GB peak RSS is not a reason to move it). `PRQ-18` installs it; `remote`
  stays as an escape hatch only. Live S1 steps need about 2.5 GB of headroom next to the job. The earlier reading
  (Mac, `engine: remote`) rested on a reachability probe that tried ports 8000, 8765 and 22, never the protocol's 8790.
* **P3: the S1 state budget is 300 approx-tokens.** It is the largest count that fits 463 Laya tokens for the worst text
  type (code); prose would allow 540. The effective cap is `min(verifier.s1.max_state_tokens, 300)`.

## Root steps on runners nobody prepared

On a persistent runner (this one), every root step is a human step. `prereqs.sh` runs them, and `l4 doctor --fix` never
escalates (L4-DOC-002).

On a disposable runner, a GitHub-hosted VM that serves one job and is then destroyed, the generated job first runs the
vendored `.l4/bin/l4-setup` (L4-PRV-020..022). It installs uv and a user-space bubblewrap without root. It may run
exactly one root command, `sudo -n sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, and only when all of these
hold:
- the runner is disposable (`RUNNER_ENVIRONMENT=github-hosted` or `CI_DISPOSABLE_ENVIRONMENT=true`);
- the user-space bwrap fails its self-test;
- the setting is `1`;
- `L4_PROVISION_ROOT` is not `0`;
- `sudo -n true` works.

Ubuntu 24.04's AppArmor default blocks unprivileged user namespaces even for an apt-installed bwrap. 22.04 needs no root
at all [V, docs/spikes/06].

The setting lowers a kernel hardening measure for the rest of that VM's life, which is acceptable only because the VM is
thrown away. Set `L4_PROVISION_ROOT=0` to forbid the command on hosted runners too. On this runner `l4-setup` never
runs the command: it prints it, with the reason. It never runs `apt-get install`.

## Authentication (human steps)

The harness and these scripts never log in. Pick per adapter (decision Q3: subscription for Codex/Claude, API keys
for OpenCode/OpenRouter and the judges):

| Adapter | Option | Where |
|---|---|---|
| claude-code | `claude setup-token` on your workstation → masked CI variable `CLAUDE_CODE_OAUTH_TOKEN` (on GitHub: a secret of the environment `l4`) | GitLab → project → Settings → CI/CD → Variables; GitHub → Settings → Environments |
| codex | as the runner user on the host: `sudo -u gitlab-runner -H codex login --device-auth` (stores `~/.codex/auth.json`) | host |
| opencode | already configured with provider `magnitude`; for hosted models add `OPENROUTER_API_KEY` as a masked CI variable | host / CI variables |
| kiro-cli | `sudo -u gitlab-runner -H kiro-cli login`, or `KIRO_API_KEY` (Pro tier+) as a masked CI variable | host / CI variables |

`prereqs.sh` (PRQ-15) and `l4 doctor` report each adapter as ready / installed-not-authenticated / missing.

### Incident 2026-10-07: the runner's Claude login was wiped (one process per login, L4-FAC-008)

**What happened.** At 2026-10-07 21:33:12, 3 s after CI l4 job 6045 started, `~gitlab-runner/.claude/.credentials.json`
was rewritten with an empty `refreshToken` and `expiresAt: 0`, so the runner had no Claude login until a human logged
in again. The same had been seen on 2026-10-05.

**Cause.** Claude, Codex and Kiro refresh their stored OAuth login themselves, with a single-use refresh token. Out-of-CI
runs as gitlab-runner (the free-model measurement, the M1.14 `l4 eval` with claude-code as the fixed judge) share
`~/.claude` with the CI jobs and checked for idleness only when they started. Two processes found the token expired at
the same moment and both refreshed it; the loser's refresh was refused and it cleared the stored credentials (inferred
from the timing and the empty fields [I]). The
existing per-login limit did not stop it: the lock files lived under `$L4_CACHE/locks` (the out-of-CI runs use another
cache, so they locked other files), the limit honoured `max_concurrency` (more than one process allowed), and the login
check, the hello probe and `doctor` spawned the CLI without the lock.

**Fix (merge of `cred-lock`).** Every `l4` process of the runner user (CI jobs, `l4 eval` and its `l4 run` cells,
`l4 probe`, `l4 doctor`, `doctor --live`) takes one lock per login in `~/.cache/l4/locks` of the OS user (mode 0700,
whatever `$L4_CACHE`, `$XDG_*` or the entry point), keyed by the credential directory the spawned CLI uses
(`$HOME/.claude`, `$HOME/.codex`, Kiro's data store). The limit is exactly one process for claude-code, codex and kiro-cli
unless `auth: api_key`. The lock is held around the whole probe ladder of a profile (binary, auth, quota, hello), the
`doctor` readiness probe and each agent run. A process that does not get it waits up to
`availability.login_lock_wait` (20m), prints `[l4] login: waited …` and ledgers `availability.login_wait`; after that the
profile is `unavailable: another process holds the <adapter> login` and the next profile of the chain is used.

**What it does not cover.**
- The lock only serialises processes that run a harness with it. A consumer repository runs the harness its `.l4`
  pins: run `l4 upgrade` in every repository this runner serves (and in the dummy whose `.l4/bin/l4` the free-model
  driver calls) before relying on it.
- A bare `claude` / `codex` / `kiro-cli` call does not take the lock, and neither do `scripts/runner/{hello,
  sandbox-probe,record-probes,ci-probe,inspect,prereqs}.sh`. Do not drive a CLI by hand on the runner while jobs or an
  eval run, and do not copy a login between users.
- When an `l4` process is killed (SIGKILL, or SIGTERM, which it does not trap) its lock is freed at once. A sandboxed
  agent run dies with it (`bwrap --die-with-parent`); an unsandboxed probe step (`claude auth status`, the hello
  prompt) can outlive it by up to its probe timeout [I].

**Re-login.** `l4 doctor` ENV-014 warns when a stored login looks wiped. Log in again as the runner user, in a login
shell (`-i`, which loads the runner user's own PATH):

```bash
sudo -iu gitlab-runner
claude          # then type /login and follow the link
```

| Adapter | Command (as the runner user) |
|---|---|
| claude-code | `sudo -iu gitlab-runner`, run `claude`, type `/login` |
| codex | `sudo -iu gitlab-runner codex login --device-auth` |
| kiro-cli | `sudo -iu gitlab-runner kiro-cli login` |

## Azure Pipelines agent (2026-10-09)

The host also runs an Azure Pipelines self-hosted agent, next to the GitLab runner, for the Azure DevOps organisation
`example-org` (project `SampleProject`), set up with `scripts/runner/mk-azdo-agent.sh --apply`:

| Thing | Value |
|---|---|
| Pool | `agentic` (organisation pool id 12, `autoProvision: false`), queue `agentic` (id 142) in `SampleProject` only, created with `authorizePipelines=false`: a pipeline runs here only when its YAML names `pool: agentic` and someone authorizes that pipeline once |
| Agent | `l4-agent`, version 5.280.0, service `vsts.agent.example-org.agentic.l4-agent.service` |
| OS user | `azdo-agent` (system user, own group, home `/home/azdo-agent` mode 750, not in `docker`). gitlab-runner's home is 750, so Azure jobs cannot read the agent-CLI logins; `azdo-agent.sh --check` re-verifies it |
| Credential | registered with a one-day PAT (Agent Pools read & manage), revoked right after; the agent now uses its own key |
| Resources | idle about 170 MB RSS. The host has 4 vCPU; `free -m` reported 3.8 GB earlier and 5.7 to 5.9 GB on 2026-10-09 (the hypervisor seems to resize it). One Azure job can run at the same time as one GitLab job: heavy builds on both at once will compete for memory |

Smoke test: `scripts/runner/mk-azdo-agent.sh --smoke` runs one job on the pool and touches no repository. It creates a
classic release pipeline with no artifacts and one agent job on queue `agentic`, runs it once, prints the job's checks
and deletes the pipeline again. From inside the job it checks that it runs as `azdo-agent`, not in `docker`, cannot
use docker, has no passwordless sudo and cannot list `/home/gitlab-runner`. It exits non-zero if any check fails.
First run 2026-10-09: release 274 on `l4-agent` v5.280.0 passed all five checks; the pipeline was deleted and no
build ran in the project. A YAML pipeline on a branch was not used: the `az` login cannot read the SampleProject
repositories (404).

What it is not: L4 does not run on Azure DevOps. The harness has no Azure DevOps forge (PRs, labels, pipeline API) and
no Azure Pipelines CI template, and Azure jobs here have no agent-CLI logins. Running L4 on the Azure repos needs that
adapter first (and the agent would then run as a user that holds logins, with the exposure the GitLab instance runner
has today).

Remove: `scripts/runner/mk-azdo-agent.sh --remove` (unregisters and removes the service; the pool, the user and
`/home/azdo-agent` stay; `sudo userdel -r azdo-agent` and deleting the pool in Organization settings > Agent pools
drop the rest).

## Reaching the host through Mintkey

`mk-ssh.sh` needs the local Mintkey stack, a service of `connect_type: ssh` granted to the agent, and `sshpass`.
Bastion: `localhost:2222` (override `MINTKEY_BASTION`).

**Docker subnet clash (found 2026-10-03).** The bastion runs in Docker Desktop. A second compose project
(`mintkey-test`) had been given `198.51.100.0/24` from Docker's default pool, which contains the LAN `192.0.2.0/24`;
inside the Docker VM, `192.0.2.20` was routed to that bridge and every SSH attempt ended with
`failed to connect to backend 192.0.2.20:22: dial tcp …: i/o timeout`, while the Mac itself reached the host.
Diagnose with:

```bash
docker run --rm --network host alpine ip route get <runner-ip>     # must NOT show a br-… device
docker network ls -q | xargs docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}'
```

Fix applied: pin the test project's network to `203.0.113.0/24` in `<broker compose file>`
(`networks.mintkey.ipam.config`) and recreate that project (`down` + `up -d`, volumes kept). Afterwards the route is
`via 192.0.2.1 dev eth1` and `mk-ssh.sh` works.

## Open warnings (not changed automatically)

* **Memory**: the VM (KVM) uses **ballooning up to 10 GB** (maintainer, 2026-10-04); the guest's `MemTotal` grows on
  demand (observed 3801 MB → 4097 MB on 2026-10-04), so a low `free` reading is not the ceiling. Laya (2.48 GB peak RSS,
  pipeline 2549) runs on the runner. Keep `concurrent = 1`.
  (The comment in `/etc/gitlab-runner/config.toml` says 8.3 GB — it is out of date.)
* **docker group**: `gitlab-runner` is in `docker` (root-equivalent for job code), although the comment in
  `config.toml` says it is not. Confirmed live on 2026-10-05: from inside the old sandbox argv (`--ro-bind / /`, also
  with `--unshare-net`) a `connect()` to `/var/run/docker.sock` and `GET /_ping` returned `HTTP/1.0 200 OK`, because a
  read-only bind does not stop a unix-socket connect. L4's bwrap sandboxes (agent and gate) now cover `/run` (and
  `/var/run`) with a tmpfs and put back only the file `/etc/resolv.conf` points to, so the socket is masked **inside the
  sandboxes** (`l4 doctor` SANDBOX-002 and the `sandbox-probe.sh` canary check it). Anything outside the sandbox (other
  jobs of this runner, the harness process) still has the group. Removing it is the maintainer's decision, because it
  may break other jobs: `sudo gpasswd -d gitlab-runner docker`, then restart the gitlab-runner service (a running
  service keeps its groups until restarted). `prereqs.sh` PRQ-19 warns while the membership exists and never changes it.
  Residual: a daemon socket outside `/run` (for example under the runner's home) stays reachable, and abstract unix
  sockets (dbus, X11) are isolated only by `--unshare-net`, which gates get with `gates.network: none` and agent
  sandboxes (network on) do not.
* **What the sandboxes give, and what they do not give yet (HB-14, HB-16).** Since 0.4.18 both bwrap sandboxes cover the
  runner user's real `$HOME` and the runner cache `$L4_CACHE` with a tmpfs and bind back only the tool paths
  (read-only), the step's own directories and the caches, so a credential file outside the adapters' login paths
  (`~/.git-credentials`, `~/.netrc`, `~/.ssh`, `~/.config/gh`, `~/.docker`) and another unit's or project's files are not
  readable inside them (HB-16 built; L4-SEC-030..032). A tool the harness does not find under the home goes into
  `sandbox.tool_paths`. Doctor `SANDBOX-003` is the live check on the runner (canaries in the home, in another unit's
  step directory and in the lock directory), next to `SANDBOX-002` (daemon sockets). Doctor `SANDBOX-001`
  (per-profile pairwise credential separation, no ancestor environment) is specified but **not built**. The probe script
  is a manual canary, not a gate.
* **Forge setup is `l4 setup gitlab` (M1.8).** The bot token, the scoped `L4_FORGE_TOKEN`, `--secret` variables, the
  `l4 sweep` schedule, the runner check and one adoption-check pipeline are one command
  (`.l4/bin/l4 setup gitlab --project group/name --watch`, with a Maintainer's token in `$GITLAB_TOKEN`; through Mintkey
  `scripts/forge/mk-l4-setup-gitlab.sh`). It replaces the scripts below, which stay until it has had live use:
  `l4 setup gitlab --rotate --revoke-old` is the rotation; its runner row says whether the runner that takes the `l4`
  job is an instance (shared) runner, which, whatever the project's visibility, is any project's jobs next to this
  checkout, the `l4` job's token and the runner's agent logins. See [quickstart.md](../quickstart.md).
* **CI/CD variable scope (HB-2, owed on the live project).** `L4_FORGE_TOKEN` and `TYPESAFE_API_KEY` were created with
  no environment scope (`*`), so the project's own `test` job, which the hand-off commit starts and which runs code an
  agent wrote, receives them. The CI template's `l4` job now declares `environment: {name: l4, action: prepare}`, and
  `scripts/forge/gitlab_bot_token.py` and `scripts/forge/gitlab_ci_var_from_mintkey.py` store the variable with
  `--environment-scope` (default `l4`). Nothing was changed on the live project by that code change. To finish: update
  the include template in the project (`l4 upgrade`), run the two scripts (no scoped variable exists yet, so
  `gitlab_bot_token.py` mints a NEW token: that run is the rotation; both print a WARN while an unscoped variable of
  the same name exists), prove with a presence-only probe job on `l4/**` (`[ -n "$L4_FORGE_TOKEN" ]`:
  PRESENT in `l4`, ABSENT in `test`), then delete the unscoped variables in the UI (the old token is revoked by the maintainer). Environment
  scopes in GitLab CE 17.5 are [U]: check the Variables UI. `l4 doctor` has no scope check: GitLab's variables API
  returns the value with `environment_scope`, and the doctor does not read values. Also set `run_untagged: false` on
  runner 12 (current value [U]).
  **Done on the live project 2026-10-05** ([docs/live/README.md, "Handbook fixes live"](../live/README.md)): CE 17.5
  supports environment scopes; `L4_FORGE_TOKEN` (new token id 63) and `TYPESAFE_API_KEY` exist only with scope `l4`,
  the unscoped ones are deleted, and a presence-only probe printed ABSENT in a job without the environment and PRESENT
  in environment `l4`. Runner 12 already has `run_untagged: false` [V, `GET runners/12`]. The old `l4-bot` token id 62 was
  revoked on 2026-10-05 (`DELETE projects/118/access_tokens/62` → 204); only id 63 is active.
* **OpenCode user config** loads two MCP servers through `npx -y …@latest` (firecrawl, context7). The harness runs
  OpenCode with an isolated config (`--pure` / `OPENCODE_CONFIG_CONTENT`) so jobs do not depend on them.
* **`L4_FORGE_TOKEN` seen in an argv (2026-10-04, owed).** The first version of `ci-probe-refs.sh`, used for the G7 run
  (pipeline 2548, job 5429), masked the token by value, which put the value in `sed`'s argv on `l4-runner` for the
  length of that job. The committed script masks by shape and keeps the value out of every argv. That first version was
  on the deleted probe branch and could not be re-read. **Rotate `L4_FORGE_TOKEN`** (the `l4-bot` token) unless the
  runner VM is single-tenant; this is a human action and has not been done by the harness.
  **Rotated 2026-10-05** (`mk-gitlab-bot-token.sh --rotate`, new token id 63); the old token id 62 was revoked the same day,
  so the rotation is complete.

### Laya crashes with exit code -4 (SIGILL): the VM exposes no AVX (2026-10-06)

* **Evidence [V]:** `lscpu` on l4-runner reports `QEMU Virtual CPU version 2.5+`, and `/proc/cpuinfo` has no
  `avx`, `avx2`, `fma` or `f16c` flag. The kernel log has `traps: laya-serve[…] trap invalid opcode … in
  libtorch_cpu.so` at 08:03:36 and 08:05:58 on 2026-10-06, the two M1.10 rounds where step 8 was `unavailable
  (RemoteProtocolError)`. The laya tool venv (torch `2.14.1+cpu`, `libtorch_cpu.so` dated 2026-10-04 12:36) did not
  change between the runs that worked (M1.5, M1.6, M1.9) and the ones that crashed. Uptime was 3 days, so the VM was
  not restarted in between.
* **Reading [I]:** the CPU torch build reaches an AVX instruction on some code paths only, which is why earlier runs and
  a restarted `laya-serve` could answer. A generic QEMU CPU model hides the host's vector extensions from the guest.
* **Effect:** none on verdicts. S1 never decides, and the harness records `unavailable` and goes on.
* **Fix (maintainer, hypervisor):** give the VM the host CPU model (`-cpu host` / libvirt `host-passthrough`, or at
  least a model with AVX2 and FMA), then restart it. Until then, prefer Jev or no S1 engine on this runner.
* **Harness follow-up:** a doctor warning when a `laya-local` profile is configured and the CPU lacks `avx2`.

### Free resources for L4 roles (inventory, 2026-10-06)

Evidence: [free-inventory-2026-10-06.txt](free-inventory-2026-10-06.txt) (one hello per model in the harness's
`_hello` shape, no 429 seen). Summary [V unless marked]:

* **OpenCode Zen free models, no login:** 8 of the 10 the runner lists answer `L4-OK` (big-pickle, space-bunny-free,
  longcat-2.5-preview-free, mimo-v2.6-flash-free, ling-3.1-flash-free, muse-spark-1.3-contributor-free,
  nemotron-3-ultra-free, nemotron-3.5-lightning-free). `fledge-alpha-free` answers 403 `FreeTierError` "not available in
  your country" (the adapter files this under `auth`, which is the wrong reason); `ling-3.0-flash-fin-free` answered 400
  "Endpoint is unavailable" after 81 s. Zen documents no rate limit for free models. Only Space Bunny and LongCat are
  zero-retention; the others may use prompts to improve the model, and Muse Spark trains Meta models on them
  ([Zen docs, Privacy](https://opencode.ai/docs/zen)).
* **Jev 1.13 Free on Zen** (`POST https://opencode.ai/zen/v1/systemone`, model `jev-1.13-free`) answered from the runner
  with **no API key** (HTTP 200, `cost "0"`); a wrong key gets 401. The harness cannot use it yet: `engine: jev` refuses to
  start without a key variable and `engine: remote` needs `GET <base_url>/health` = 200 (Zen: 404).
* **magnitude** (OpenAI-compatible, on the maintainer's Mac `192.0.2.10:10100`): `qwen3.6-35b-a3b:gguf:q5` passes the
  hello in 7.3 s through the runner user's own OpenCode config. It is free only while the Mac is up. The harness's
  isolated OpenCode config (an empty `XDG_CONFIG_HOME`) has no provider block, so `magnitude/*` profiles fail today.
* **Laya:** still no AVX/AVX2 (`QEMU Virtual CPU version 2.5+`, flag `vmx` and vendor `GenuineIntel` point to an Intel
  host [I]); the CPU model was not changed.
* **Codex Plus:** 5 h window 1 % used, weekly 4 % used (zero-cost `account/rateLimits/read`), plus one unused
  "Full reset (Weekly + 5 hr)" credit that expires 2026-10-29. **Claude Pro:** `claude -p /usage` on 2.1.288 returns no
  windows, so the quota step cannot read them.
