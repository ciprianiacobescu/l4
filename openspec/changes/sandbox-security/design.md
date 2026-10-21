## Context

SPEC §18 requires two OS-level sandboxes (agent, gate) because an environment allow-list alone does not stop same-user code from reading `/proc/<ancestor>/environ`, `.git/config` and login files. Decision Q6 (SPEC §22): bubblewrap, installed by the maintainer on `l4-runner`; until then doctor fails `SANDBOX-001`. The user's goal is easy install: the runner is assumed to have the tools, and if it is a shell runner without `bwrap` the harness must say exactly what is missing (runner-provisioning change 12 may install user-local tools; `bwrap` needs root or a distro package, so it is reported, not installed).

Evidence labels follow SPEC: [V] verified, [I] design decision, [U] must be confirmed by a test or spike before relying on it.

## Goals

- Run every agent and every gate command inside a bubblewrap sandbox when `bwrap` works on the runner (M1).
- Fail closed: no usable sandbox means no agent and no gate, doctor exit 3 (M1).
- Allow `mode: none` only as an explicit, loudly reported, ledger-recorded risk acceptance (M1).
- One `Sandbox.wrap()` choke point so no later change can start an agent or gate unsandboxed by accident.
- Provide the shared SEC helpers other changes import (env, git hardening, safe XML, protected paths, isolation flags).

## Non-Goals

- Container and separate-user modes are designed (interface, config validation) but implemented in M2.
- macOS isolation (NFR-005): local development uses `mode: user`/`container` with a doctor warning; not in M1.
- Declaring the sandbox GA (blocked on the change-0 spikes, L4-SEC-005 part h).
- Installing `bwrap` (system package; reported by doctor with the install hint only).

## Decisions

### D1. Module layout and public names
- `l4.sandbox.base`: `SandboxKind = Literal["agent","gate"]`; `@dataclass(frozen=True) SandboxSpec(kind, worktree: Path, git_common_dir: Path, tmp_dir: Path, home_dir: Path, profile: str | None, credential_paths: tuple[Path,...], caches: tuple[CacheMount,...], network: bool, extra_ro_binds: tuple[Path,...])`; `CacheMount(path, env, read_only)`; `WrappedCommand(argv: list[str], env: dict[str,str])`; `class Sandbox(Protocol): name: str; def available(self) -> Availability; def wrap(self, argv: Sequence[str], spec: SandboxSpec, env: Mapping[str,str]) -> WrappedCommand; def describe(self) -> str`; `class SandboxUnavailable(Exception)`.
- `l4.sandbox.env` (the one agent/gate env builder; agent-factory's `build_env` wraps it): `build_agent_env(profile: l4.config.schema.Profile, host_env: Mapping[str,str], spec: SandboxSpec) -> dict[str,str]`, `build_gate_env(host_env, spec) -> dict[str,str]`, `ALLOWED_PASSTHROUGH = ("PATH","LANG","LC_ALL","LC_CTYPE","TZ","TERM","HTTP_PROXY","HTTPS_PROXY","NO_PROXY","http_proxy","https_proxy","no_proxy")`. Profile credential variables are the names returned by bootstrap-core's `l4.config.validate.credential_env_names(profile)` (names only in config, L4-CFG-002); `PATH` is runner-provisioning's `l4.provision.runner.harness_path(...)` (L4-PRV-016).
- `l4.sandbox.bwrap`: `class BwrapSandbox(Sandbox)` with `build_argv(argv, spec) -> list[str]`.
- `l4.sandbox.none`: `class NoSandbox(Sandbox)`; its constructor raises `SandboxUnavailable` unless `allow_none` is true.
- `l4.sandbox.select`: `select_sandbox(cfg: l4.config.schema.SandboxCfg, platform: str, runner=subprocess.run) -> Sandbox` implementing the `auto` order bwrap, container, user and raising `SandboxUnavailable` with a message naming what is missing and how to fix it.
- `l4.sandbox.probe`: `run_probes(sandbox, cfg, profiles, canaries) -> list[ProbeFinding]`.
- `l4.doctor.checks_sandbox`: `check_sandbox_001(ctx) -> CheckResult` registered with the doctor registry from bootstrap-core.
- `l4.security.hardening`: `HARDENED_GIT_ARGS` and `COMMIT_ARGS` re-exported from state-vcs-locks' `l4.vcs.git` (`HARDENING`, `--no-verify`; `vcs/git.py` is the only module allowed to spawn git, so the flags are defined there once), `safe_parse_xml(data: bytes, max_bytes=8_000_000) -> ElementTree.Element`, `safe_load_yaml`, `safe_load_json`. Shared `.git/config` hashing and restore are state-vcs-locks' `Git.config_hash()` and `GitConfigGuard`; this change specifies the requirement (L4-SEC-006) and owns the tests that assert it.
- `l4.security.protected`: `CONTRACT_PROTECTED_GLOBS`, `is_protected(path, odd_forbidden) -> str | None` (returns the matching glob), `revert_protected(worktree, changed, git) -> list[Violation]`.
- `l4.security.sources`: `PromptSource` enum {`harness_template`, `unit_file_at_head`, `answered_question`, `lesson`, `gate_command`}, `assert_allowed(section_sources)` raising `PromptSourceNotAllowed`.
- `l4.security.trust`: `is_member_access(level) -> bool` (Developer/Write and above).
- `l4.security.isolation`: `isolation_flags(adapter: str, auth: str, allow_repo_config: bool) -> list[str]` and `protected_agent_paths(adapter) -> list[str]`.

### D2. bubblewrap argument shape (SPEC fixes only `--unshare-pid --proc /proc`; the rest is [I])
Gate sandbox argv, in order: `bwrap --die-with-parent --new-session --unshare-pid --unshare-ipc --unshare-uts --clearenv`, then `--proc /proc --dev /dev --tmpfs /tmp`, system read-only binds (`--ro-bind /usr /usr`, `--ro-bind /etc /etc`, `--symlink usr/bin /bin`, `--symlink usr/lib /lib`, `--symlink usr/lib64 /lib64` when those are symlinks on the host), `--tmpfs <real HOME>` hiding the runner's home, `--bind <home_dir> <home_dir>` (the private HOME), `--bind <worktree> <worktree>`, `--ro-bind <git_common_dir> <git_common_dir>`, `--bind <tmp_dir> <tmp_dir>`, cache mounts (`--bind`, or `--ro-bind` when `read_only`), `--setenv K V` per allow-listed variable, `--chdir <worktree>`, `--`, argv. `--unshare-net` is added when `gates.network: none`. Agent sandboxes additionally `--bind` only that profile's `credential_paths`. A fresh `--proc /proc` inside the new PID namespace hides ancestor PIDs, which is what defeats `/proc/<ppid>/environ` reads.
Alternatives rejected: `--ro-bind / /` plus tmpfs overlays on known credential paths (a deny-list: leaks unknown files such as `~/.ssh`, `~/.git-credentials`, `~/.config/glab-cli`); a Docker container per command (needs the Docker socket on shell runners, slow, SPEC reserves it for M2 `container` mode).

### D3. Tools living under the runner's home
The reference runner installs `uv`, node and agent CLIs user-locally (`~/.local/bin`, `~/.local/share/uv`, `~/.nvm`). Hiding the real home would hide them. Decision [I]: read-only bind each directory of runner-provisioning's `harness_path` (`~/.local/bin`, `$L4_HOME/node/bin`, `$L4_CACHE/tools/*/node_modules/.bin`, `~/.opencode/bin`, then the inherited `PATH`) that sits under the real HOME, minus any `credential_paths`, and set `PATH` inside the sandbox to the same directories. No new config key is introduced (a SPEC amendment would be needed). [U]: whether `uv`'s managed Python and node's global prefix survive this; confirmed by the live smoke test (task 1.14) on `l4-runner`.

### D4. Fail closed, with one choke point
`select_sandbox` is the only constructor path used by the orchestrator and gate runner; both call `sandbox.wrap(...)` for every spawn. `NoSandbox` exists only when `mode: none` and `allow_none: true` (D5). A repository test asserts no module under `src/l4/{agents,gates,implementer}` calls `subprocess` directly except through `Sandbox.wrap` (static grep test). Availability is established by actually running `bwrap --unshare-pid --proc /proc --ro-bind / / -- true` (not by `which`), because unprivileged user namespaces can be blocked (e.g. Ubuntu 24.04 AppArmor `kernel.apparmor_restrict_unprivileged_userns` [I]; spike row "bubblewrap on GitHub-hosted ubuntu-24.04" settles it [U]).

### D5. `mode: none`
SPEC: refused unless `sandbox.allow_none: true`, reported as an accepted risk on every doctor run. Task statement: allowed only "when sandbox.mode is explicitly none". Resolution: both must be set. `mode: auto` never degrades to `none`. When accepted, doctor emits status `warn` with message `SANDBOX DISABLED (accepted risk): agents and gates run as the harness OS user and can read its secrets`, the console prints the same line at run start, and the ledger gets `sandbox.risk_accepted{mode:"none", by:"config"}` once per run.

### D6. SANDBOX-001 probes
Canary approach: the probe creates (in a temp dir outside the worktree) a fake credential file per profile, a fake harness secret placed into the probe parent's environment (`L4_PROBE_SECRET_<random>`), and a fake token inside a copy of `.git/config`-style userinfo URL check. It runs `/bin/sh -c` probe scripts inside each sandbox using only POSIX tools: `test -e <canary path>`, `grep -a <random> /proc/$PPID/environ /proc/1/environ /proc/*/environ`, `env | grep L4_`, scan `$GIT_COMMON_DIR/config` for `://user:secret@`. Any hit is a finding; findings carry only paths and variable names, never values. Agent-sandbox probes additionally assert own-credential visibility, cache writability and that the LLM API host resolves (skipped offline with a warning).

### D7. Isolation flags (L4-SEC-002) [V flags per SPEC research/02, re-confirmed by contract tests against the real CLIs]
`isolation_flags` returns: claude-code/api_key `["--bare"]`; claude-code/subscription `["--strict-mcp-config"]` plus protected agent-config paths; codex `["--ignore-user-config"]`; opencode `["--pure"]`; kiro-cli `["--agent", "l4-harness"]` [U: exact flag; confirm in spike]. `allow_repo_config` returns `[]`. Adapters (agent-factory) must call this function; `tests/contract/test_agent_isolation.py` asserts each adapter's argv includes it.

### D8. Hardened XML without a new dependency
SPEC suggests `defusedxml`. The project dependency set is fixed (click, pydantic, PyYAML, httpx). `safe_parse_xml` rejects any input containing `<!DOCTYPE` or `<!ENTITY` (case-insensitive, after BOM/whitespace) and enforces a size limit before handing bytes to `xml.etree.ElementTree`. Alternative: add `defusedxml` (an amendment to bootstrap-core's `pyproject.toml`); rejected for now to keep the dependency list stable, revisit if bootstrap-core agrees.

### D9. Protected paths
`CONTRACT_PROTECTED_GLOBS` = `.github/workflows/**`, `.gitlab-ci.yml`, `.gitlab/**`, `.l4/**`, `.claude/**`, `.mcp.json`, `.codex/**`, `opencode.json`, `.kiro/agents/**`, `.kiro/settings/**`, `.serena/project.yml`, `.serena/memories/harness/**`. Matching uses `pathlib.PurePosixPath.full_match`-equivalent glob semantics implemented once in `l4.security.protected.glob_match` (Python 3.11 lacks `full_match`).

## Risks

- R1 [U] Unprivileged user namespaces may be disabled on the runner: mitigated by the actual-run availability probe and a clear doctor message.
- R2 [U] Agent CLIs may not work against a read-only `.git`, or inside bubblewrap with their own sandboxes (spike rows). Mitigation: M1 live test with the chosen real agent; if it fails, record in `docs/spikes/` and adapt flags.
- R3 [I] The PATH-derived read-only binds could expose a credential-bearing directory placed on PATH. Mitigation: exclude `credential_paths` and warn in doctor when a PATH directory contains dotfiles named like known credentials.
- R4 [U] Playwright/Chromium inside bubblewrap (SCN-SPK-01) and container-backed `serve` (SCN-SPK-02) are owned by change 0; this change ships no e2e sandbox claim.
- R5 Residual: an agent's own credential is readable by code the agent runs inside its sandbox; documented (part h).
