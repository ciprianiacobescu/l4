## Context

SPEC section 1 lists runtime prerequisites (git >= 2.40, uv, Python >= 3.11, Node >= 20.19 for OpenSpec 1.14.0 [V], each agent CLI, bubblewrap, ...) that doctor checks
(ENV-001..008, SANDBOX-001). The reference runner is a shell executor: jobs run as the `gitlab-runner` user in a shared filesystem, `run_untagged: false`, tags
`agentic, ai, opencode`, linux/amd64, no SSH. The maintainer wants: run a script or a couple of commands, add the harness to an existing project, and if the runner lacks tools, install
them (user-locally) and carry on. Facts already paid for:

- [V 2026-10-03, job log] `Running on gitlab-runner...` followed by `ERROR: Job failed: prepare environment: exit status 1. Check https://docs.gitlab.com/runner/shells/#shell-profile-loading`
  when the runner user's `~/.bash_logout` runs `clear_console`. Nothing of ours runs before it.
- [V doc] GitLab does not set `CI_DISPOSABLE_ENVIRONMENT` on `shell` and `ssh` executors (all others do) and exposes no executor-type variable, so a persistent shell runner is recognised by
  `GITLAB_CI=true` with `CI_DISPOSABLE_ENVIRONMENT` unset. GitHub-hosted runners report `RUNNER_ENVIRONMENT=github-hosted` [D, confirm in spike 19].
- [V] OpenSpec 1.14.0 needs Node >= 20.19 and must run from a harness-owned prefix, never `npx` (L4-OSP-001). `$L4_CACHE` is used by the SPEC but never given a default; bootstrap-core's `cache_root` (closed Q-bc-1) defines it as `$XDG_CACHE_HOME/l4`
  falling back to `~/.cache/l4` [I] and introduces `$L4_HOME` = `~/.local/share/l4` [I] for runtimes that are not caches (Node).
- SPEC says doctor `--fix` "applies the listed safe fixes only" and "never silently installed in CI". This change adds a new, explicit, logged, opt-in category of fixes.

## Goals

- Adoption in one command: `curl -fsSL <raw-url>/<sha>/install.sh | L4_REF=<sha> L4_REPO_URL=<url> bash -s -- init --ci gitlab`, or `uvx --from git+<url>@<sha> l4 init --ci gitlab` when uv exists.
- A shell runner repairs its own missing user-space tools in the first pipeline job, once, idempotently, offline-safe.
- The human is told precisely what only a human can do: sudo commands, logins, masked CI variables.
- Zero privilege escalation, zero authentication, zero secrets or e-mail in output, zero profile edits.

## Non-Goals

- Installing anything that needs root (bubblewrap, git, Docker, podman): printed only.
- Logging in to any service, creating tokens, writing credential files, or setting CI variables.
- Installing Laya, Serena, Playwright browsers or gitleaks (their doctor checks stay warn-level; a later change may extend the catalog).
- Windows. macOS gets the same user-local behaviour for development (darwin-arm64/x64 Node tarballs) but is not a runner target (L4-NFR-005).
- Changing runner configuration (`.bash_logout`, `config.toml`, timeouts): documented, never done by the harness.

## Decisions

### D1. Bootstrap shape: `install.sh` is both the human one-liner and the CI entry

`install.sh` (repo root, POSIX-ish bash, `set -euo pipefail`) does: validate `--ref`/`L4_REF` (40 hex) and `--repo`/`L4_REPO_URL`; check git present and >= 2.40 (else print the sudo command, exit 3); if `uv` is not
found in the harness search path, download the official uv installer to a temp file, log its SHA-256, run it with `UV_NO_MODIFY_PATH=1` (so shell profiles stay untouched) and `UV_INSTALL_DIR=~/.local/bin`;
then `exec uvx --from "git+$REPO@$REF" l4 "$@"`. This solves the chicken-and-egg: `l4 doctor --fix` runs through `uvx`, which needs uv, so uv is installed by the script, and again by `--fix` only when `l4` was
started some other way (vendor mode, pip). The same script is usable inside the CI job as `bash install.sh doctor --ci --fix` when the runner has no uv at all (documented as the first-run recipe; the generated YAML keeps the
one-line `l4 doctor --ci --fix`, which assumes uv or a previous bootstrap).
Alternatives: (a) a `.l4/ci/bootstrap.sh` generated into the repo: widens the L4-INS-002 footprint and the file is trusted from the base branch only (L4-CFG-004), rejected; (b) treat uv as a hard
prerequisite: simplest, but fails the "one command" goal on a fresh VM, rejected; (c) a pip/pipx install: needs Python tooling the machine may not have, rejected. Open point: the host of the raw URL depends on SPEC Q1
(harness repository location), so `L4_REPO_URL` is required until Q1 is decided and the script then bakes a default.

### D2. Module layout and key data structures (all under `src/l4/provision/`)

- `catalog.py`: constants `NODE_MIN = (20, 19, 0)`, `NODE_VERSION = "22.22.0"` [V: the same major/minor runs on the dev machine; tarball URL `https://nodejs.org/dist/v22.22.0/node-v22.22.0-<os>-<arch>.tar.xz` and
  `SHASUMS256.txt` existence are [U], confirmed by task 1.6], `OPENSPEC_DEFAULT = "1.14.0"` [V], `CODEX_DEFAULT = "0.160.0"` [V];
  `@dataclass(frozen=True) class ToolSpec: name: str; kind: Literal["uv","node","openspec","agent"]; probe_argv: tuple[str, ...]; min_version: str | None; needs_root: bool`;
  `INSTALLERS: dict[str, InstallerSpec]` with `InstallerSpec(url: str | None, argv: tuple[str, ...], env: dict[str, str], dest_hint: str)`; `required_tools(cfg) -> list[ToolSpec]` (Node and OpenSpec only when
  `openspec` is an active framework; an agent only when one of its profiles is in some role chain, fallbacks included); `ROOT_PREREQS = {"bwrap": ..., "git": ...}` with per-distro commands keyed by `/etc/os-release` `ID`/`ID_LIKE`.
- `runner.py`: `class Paths(local_bin, l4_home, l4_cache)` with `Paths.from_env(env)`; `harness_path(paths, inherited) -> str` (order: `~/.local/bin`, `$L4_HOME/node/bin`, `$L4_CACHE/tools/*/node_modules/.bin`,
  `~/.opencode/bin`, inherited PATH); `find_tool(name, paths, env) -> Path | None`; `@dataclass class FixAction(tool, reason, target, commands: list[str], needs_root: bool, status: Literal["planned","applied","already present","manual","failed","skipped"], message: str)`;
  `plan_fixes(cfg, paths, env, platform) -> list[FixAction]`; `apply_fixes(actions, *, fetcher, runner, lock) -> list[FixAction]`; `resolve_self_provision(cfg, env) -> bool`; `scrub_env(env) -> dict[str, str]`;
  `class Fetcher(Protocol): download(url, dest) -> Path; reachable(host) -> bool` with `HttpxFetcher` (httpx, timeouts 10 s connect / 300 s read) and a test double; `class CommandRunner(Protocol): run(argv, env, cwd, timeout) -> CompletedProcess`;
  `class OfflineError(Exception)` and `class IntegrityError(Exception)` (both map to exit 3); `provision_lock(paths, wait_s=600)` context manager using `fcntl.flock` on `$L4_CACHE/locks/provision.lock`.
- `readiness.py`: `class AdapterState(StrEnum): READY = "ready"; INSTALLED_NOT_AUTHENTICATED = "installed-not-authenticated"; MISSING = "missing"`; `@dataclass class AdapterReadiness(profile, adapter, state, steps: list[str])`;
  `adapter_readiness(profile, paths, env, runner) -> AdapterReadiness`; `HUMAN_STEPS: dict[tuple[str, str], list[str]]` keyed by `(adapter, auth)`; `sanitize_status(adapter, raw) -> dict[str, object]` returning only
  `logged_in`, `auth_method`, `plan`.
- `src/l4/doctor/checks_provision.py` (framework in bootstrap-core): `register(Check(...))` for `PRV-001` (warn: adapter readiness table, one line per profile) and `PRV-002` (warn: root-only prerequisites with the sudo command), and the fix handler
  `fix_provision(ctx) -> FixOutcome` attached with bootstrap-core's `registry.attach_fix(check_id, Fix(kind="install", scope="provision", apply=fix_provision))` to ENV-001, ENV-003, ENV-004 (these three get `--fix` = "install user-local, L4-PRV-004/005" in the SPEC table). Registry API reconciled with bootstrap-core D12 by the cross-change review.
- Directory contract: uv `~/.local/bin/uv`; Node `$L4_HOME/node/{bin,lib,...}` plus `$L4_HOME/node/.l4-version`; OpenSpec `$L4_CACHE/tools/openspec-<ver>/node_modules/.bin/openspec` (identical to L4-OSP-001);
  Codex `$L4_CACHE/tools/codex-<ver>/node_modules/.bin/codex`; claude `~/.local/bin/claude` [V on the dev machine, `command -v claude`]; opencode `~/.opencode/bin/opencode` [V on dev machine]; kiro-cli `~/.local/bin/kiro-cli` [U].

### D3. Install mechanics per tool (exact commands; evidence labels kept)

| Tool | Command (user-local, no sudo) | Evidence |
|---|---|---|
| uv | download `https://astral.sh/uv/install.sh` to a temp file, run `sh <file>` with `UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR=$HOME/.local/bin` | URL and switches [D], confirm in spike 22 |
| Node | `https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-{linux-x64,linux-arm64,darwin-arm64,darwin-x64}.tar.xz`, verify against `SHASUMS256.txt` of the same directory, extract to `$L4_HOME/node.tmp.<pid>` then `os.rename` to `$L4_HOME/node` | URL scheme [U], checksum file [U] (task 1.6) |
| OpenSpec | `<harness node>/bin/npm install --prefix $L4_CACHE/tools/openspec-1.14.0 @fission-ai/openspec@1.14.0` with `PATH` = harness path | command [V, L4-OSP-001] |
| Codex | `npm install --prefix $L4_CACHE/tools/codex-<ver> @openai/codex@<ver>` (needs the same Node) | package and version [V, local binary 0.160.0] |
| Claude Code | download `https://claude.ai/install.sh`, run `bash <file>` (installs to `~/.local/bin`) | [D], confirm in spike 22 |
| OpenCode | download `https://opencode.ai/install`, run `bash <file> --no-modify-path` | URL [D]; switch name [U]; install dir `~/.opencode/bin` [V on the dev machine] |
| kiro-cli | download `https://cli.kiro.dev/install`, run `bash <file>` | [U] (not installed on the dev machine; M2) |

Downloads go through `Fetcher` (httpx), never `curl | sh`. Vendor scripts are saved, hashed (SHA-256 logged, L4-PRV-014) and executed from the file with `scrub_env` (D6). A no-modify-path switch that is not recognised by a future
version is caught by the profile-checksum guard of L4-PRV-003 (a test compares profile files before and after).
Alternatives: system package managers (need root, rejected by the goal); `pipx`/`pip --user` for everything (Node and the agent CLIs are not Python); Homebrew-on-Linux (not present on runners); Docker images (shell executor, no).

### D4. Offline behaviour

Before the first download of a run, `Fetcher.reachable(host)` tests the host of each planned download (DNS plus TLS handshake, 10 s); an unreachable host or an `httpx.TransportError` mid-run raises `OfflineError(tool, host, manual_command)`, which
`apply_fixes` turns into a `failed` action with message `cannot reach <host> to install <tool>; run manually: <command>`; no directory for that tool is created (temp dirs are removed); exit code 3. If `plan_fixes` returns only `already present` actions the
network is never touched (L4-PRV-013). Alternative: retry with back-off; rejected, a missing network in a runner job is a configuration problem, not a transient one (one retry for HTTP 5xx only).

### D5. `--fix` in CI: scope and resolution

`ci.self_provision` is `auto | true | false` (default `auto`). Render time (forge-and-ci template): `true` -> `l4 doctor --ci --fix`; `false` -> `l4 doctor --ci`; `auto` -> `--fix` on GitLab, no `--fix` on GitHub (hosted runners are ephemeral and ship tools).
Run time: `resolve_self_provision(cfg, env)`: `true`/`false` as is; `auto` -> false when `CI_DISPOSABLE_ENVIRONMENT == "true"` or `RUNNER_ENVIRONMENT == "github-hosted"`, otherwise true. With `--ci`, only provisioning fixes run; repository-mutating
fixes (CI-001 re-render, FORGE-003, GIT-*) are refused because a CI file rewritten inside a job could never be committed anyway and the base-branch trust rule (L4-CFG-004) forbids relying on it. Alternative: a separate flag `--fix=provision`;
rejected because the user-facing command is `l4 doctor --fix` and the CI line must stay short, but the internal scope is bootstrap-core's `FixScope` (`provision`, `repo`) so the CLI can grow `--fix-scope` later without breaking this contract.

### D6. Security posture

- Clean environment (L4-PRV-015): `scrub_env` keeps `HOME`, `PATH` (harness path), `LANG`, `LC_*`, `TMPDIR`, `HTTP(S)_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, `npm_config_cache` (set to `$L4_CACHE/npm`) and per-installer switches. Everything else is dropped, notably
  `L4_FORGE_TOKEN`, `L4_TRIGGER_TOKEN`, `L4_GITHUB_APP_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `CODEX_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `KIRO_API_KEY` (same set as `observability.redact_env`).
- Never root (L4-PRV-006): `grep`-style test asserts that no argv built by the module starts with `sudo|su|doas`; root-only items are `FixAction(status="manual")` with a `commands` list for display.
- Never authenticate (L4-PRV-007): `HUMAN_STEPS` (Codex step `codex login --device-auth` is [V 0.160.0: listed by `codex login --help`]; Claude `setup-token` [V research/02]; `kiro-cli login` [U]) is data, printed, never executed; the `CommandRunner` used for status probes refuses argv containing `login`, `setup-token`, `auth login` (defence in depth; test with recording fakes).
- Readiness (L4-PRV-008/009): status commands are `claude auth status` (JSON, contains an e-mail [V]), `codex login status` (exit 1 when logged out [V]), env-var presence for API-key profiles, `kiro-cli whoami` [D], `opencode` via `OPENROUTER_API_KEY` presence [I; `opencode auth list` is [U]].
  Output goes through `sanitize_status` before any print or log. `ready` means "an auth signal exists", not "the credential works": validity is `doctor --live` (LIVE-001).
- The installer URL list is code, not config, so a repository cannot redirect it (L4-SEC-006 spirit).

### D7. Atomicity, idempotence, locking

Every install writes into `<target>.tmp.<pid>` and renames to the final path; at start `apply_fixes` removes stale `*.tmp.*` siblings of its targets older than 1 h. "Already present" is decided by running the tool's probe from the harness path and comparing versions, not by directory existence.
`provision_lock` serialises concurrent jobs (shell runners share the filesystem, risk R5); after taking the lock the plan is recomputed so the waiting job installs nothing. Lock wait 600 s, then exit 3; the lock file is never deleted by the waiter.
Test policy: every network or installer interaction in unit tests goes through the `Fetcher` / `CommandRunner` doubles in `tests/unit/provision/conftest.py`; real downloads happen only in the Docker end-to-end task 1.23 and the live task 1.24.

### D8. Documentation and the `.bash_logout` failure

`docs/runner-setup.md` has sections: Quick start (the one-liner), Runner prerequisites (what only root can do: bubblewrap, git), Authentication per adapter (the human steps of L4-PRV-007), What `doctor --fix` does and never does, and
Troubleshooting (stating that the signature requires that no script output precedes the error) with the signature `ERROR: Job failed: prepare environment: exit status 1` right after `Running on <host>` and the fix `sudo mv /home/gitlab-runner/.bash_logout{,.disabled}` (cause: `clear_console` in `~/.bash_logout`;
see https://docs.gitlab.com/runner/shells/#shell-profile-loading). `l4 init --ci gitlab` prints a three-line notice with the same two strings. Doctor cannot detect the failure from inside a job (nothing runs), so there is no check; a log-matching helper is out of scope.

## SPEC amendments required by this change (SPEC.md is not edited by this drafting step)

1. Section 1, runtime prerequisites paragraph: replace "never silently installed in CI" with "installed in CI only by `l4 doctor --fix` when `ci.self_provision` resolves true; every action is logged; nothing needing root and no authentication is ever performed (L4-PRV-004..007)". Add `install.sh` to L4-INS-001.
2. Section 2.1 doctor row: `--fix` description, and `--dry-run` accepted with `--fix` (extends L4-SIM-001).
3. Section 3.2: add `ci.self_provision: auto  # auto | true | false` under `ci:`; define `$L4_CACHE` (default `~/.cache/l4`) and `$L4_HOME` (default `~/.local/share/l4`).
4. Section 15 table: `--fix` column of ENV-001, ENV-003, ENV-004 becomes "install user-local (L4-PRV-004/005)"; add `PRV-001` (warn, adapter readiness) and `PRV-002` (warn, root-only prerequisites). L4-DOC-001: "with `--ci`, `--fix` applies only provisioning fixes (L4-PRV-010)".
5. Section 16.3, shell-executor bullet: "agent CLIs are expected pre-installed" becomes "provisioned by `doctor --fix` when `ci.self_provision` resolves true, else expected pre-installed".
6. Section 23: add the SCN-PRV scenarios; section 21 table: add change 12 `runner-provisioning` (the SPEC table currently ends at 11).

## Risks

- [U] installer URLs and switches (uv `UV_NO_MODIFY_PATH`, opencode `--no-modify-path`, claude and kiro-cli installers) may differ or change; mitigation: spike 22 on the runner, contract tests replaying recorded installer outputs, and the profile-checksum test.
- Vendor installers run arbitrary code as the runner user: contained by clean env, no root, logged digest; residual risk accepted and documented (a pinned digest is impossible because vendors rotate scripts).
- Shared runner state: two projects provisioning at once (R5) is handled by the lock; a project pinning a different OpenSpec version gets its own prefix directory.
- A CI job that installs 200 MB of tools hits `build_timeout` on the very first run; mitigation: first-run is expected to be slow, doctor logs progress; the human can pre-run `install.sh` once.
- `auto` misclassifies a docker-executor runner as persistent if `CI_DISPOSABLE_ENVIRONMENT` is missing on some version: the documented override is `ci.self_provision: false`.
- bootstrap-core's doctor/registry API: reconciled (`register(Check)`, `attach_fix`, `Fix`, `FixScope`, `SAFE_FIX_KINDS` incl. `install`, bootstrap-core D12 and M1 task 1.21).
