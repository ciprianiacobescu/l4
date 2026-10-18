## Purpose

Code an agent wrote reads no file of the runner user's home, no other unit's or project's files under the runner cache,
and no environment directory a step planted something in; per-unit directories of two projects never meet.

## ADDED Requirements

### Requirement: L4-SEC-030 The real home is hidden in both sandbox kinds
Every bwrap sandbox, agent and gate, SHALL cover the runner user's real `$HOME` with a tmpfs right after the base flags
and SHALL bind back, after it, only what L4-SEC-005, L4-SEC-031 and L4-SEC-032 name; `HOME` keeps its path. A `$HOME`
that is `/`, not absolute or not an existing directory MUST make the sandbox unavailable (exit 3). Any other file of
the home, a git, SSH, gh, docker or netrc credential included, MUST NOT be readable.

#### Scenario: SCN-SEC-70 (−) Agent-written tests read no credential of the home
- **GIVEN** a runner home that holds `.git-credentials`, `.netrc`, `.ssh/id_ed25519`, `.config/gh/hosts.yml` and `.docker/config.json`, and a working bwrap
- **WHEN** a gate of a unit runs a command that reads each of them
- **THEN** every read fails inside the gate sandbox

#### Scenario: SCN-SEC-71 (−) An agent sandbox sees its own login and nothing else of the home
- **GIVEN** the home of SCN-SEC-70 plus `~/.claude.json` and `~/.codex/auth.json`, and a claude-code implementer
- **WHEN** a command in its agent sandbox reads every one of these files
- **THEN** only `~/.claude.json` is readable

#### Scenario: SCN-SEC-72 (+) The tmpfs over the home comes before every bind
- **GIVEN** a gate spec and an agent spec whose worktree, temp directory, caches and git common directory all lie under `$HOME`
- **WHEN** the bwrap argv is built
- **THEN** `--tmpfs <home>` follows the base flags, and every bind of those paths comes after it

#### Scenario: SCN-SEC-73 (−) A home of `/` is refused
- **GIVEN** `HOME=/` in the harness environment
- **WHEN** a gate is wrapped in bwrap
- **THEN** `SandboxUnavailable` is raised (exit 3) naming `HOME`, and no process starts

### Requirement: L4-SEC-031 The runner cache is hidden in both sandbox kinds
Every bwrap sandbox SHALL cover the runner cache `$L4_CACHE` with a tmpfs, after the home's and before any bind, when it
exists and lies outside `$HOME`, so that under it only the step's own worktree, private temp directory and cache mounts
are visible. Other units' and projects' step directories, worktrees, unpublished run files, the seed and the lock files
MUST NOT be visible.

#### Scenario: SCN-SEC-74 (+) A runner cache outside the home is covered and the step's directories come back
- **GIVEN** `L4_CACHE=/var/cache/l4` and a gate spec of a unit in it
- **WHEN** the bwrap argv is built
- **THEN** `--tmpfs /var/cache/l4` follows the home's tmpfs, and the worktree, the step's temp directory and each cache mount are bound after it

#### Scenario: SCN-SEC-75 (−) Another unit's step files and the lock files are not visible
- **GIVEN** a runner cache outside the home with a file in another unit's `agent-tmp`, another project's worktree and a file in `locks/`, and a working bwrap
- **WHEN** a gate and an agent of this unit read them
- **THEN** every read fails, while the unit's own worktree and caches are readable

#### Scenario: SCN-SEC-99 (−) The login and unit lock files are not readable in any sandbox
- **GIVEN** the login lock file of `l4.agents.gate.lock_root` and the unit lock file of `UnitNames.flock_path`, both existing, a runner cache under the home and one outside it, and the gate and agent specs of a unit of any adapter
- **WHEN** the bwrap argv is built (and, with a working bwrap, a command in each sandbox kind reads both files)
- **THEN** neither file is visible at its path in either kind, and the login lock directory lies under no adapter's credential path

### Requirement: L4-SEC-032 Tools under a hidden root stay usable, read-only
After the tmpfs of L4-SEC-030 and L4-SEC-031 the sandbox SHALL bind read-only each existing tool path under the home
or the runner cache: the sandbox's PATH entries and the install roots of their symlinks, the `node_modules` of a
`node_modules/.bin` entry, `$L4_HOME`, uv's Python and tool directories, the corepack home, the harness's gate plugins,
`~/.serena` for agents, and `sandbox.tool_paths`. The credential masks MUST come after them.

#### Scenario: SCN-SEC-76 (+) User-local tools are bound read-only
- **GIVEN** a home with `~/.local/bin/uv`, a symlink `~/.local/bin/claude` to `~/.local/share/claude/versions/2.1.288`, `$L4_HOME/npm/node_modules/.bin` on PATH and `~/.local/share/uv/python`
- **WHEN** the agent argv is built
- **THEN** `~/.local/bin`, `~/.local/share/claude/versions`, `$L4_HOME`, `~/.local/share/uv/python` and the harness's plugin directories are `--ro-bind` entries, `~/.local/share/uv` as a whole is not, and no tool path is bound twice

#### Scenario: SCN-SEC-77 (−) A tool bind never re-exposes a login
- **GIVEN** a PATH entry `~/.local/share/opencode/bin` and a codex agent spec
- **WHEN** the argv is built
- **THEN** the mask over `~/.local/share/opencode` comes after the bind of that PATH entry

#### Scenario: SCN-SEC-78 (+) Tools under the home run in both sandbox kinds
- **GIVEN** a working bwrap, a home outside `/tmp` with a script in `~/.local/bin` and a symlinked tool whose target is under `~/.local/share`
- **WHEN** a gate and an agent sandbox run both tools
- **THEN** both exit 0 in both kinds

### Requirement: L4-SEC-033 Configured home paths are checked at load
`sandbox.tool_paths` (both kinds) and `sandbox.setup_paths` (only the gate sandbox of a `gates.setup` command) SHALL be
lists of `~/`-relative or absolute paths, bound read-only when they exist. An entry that is `/` or `~`, contains the
runner cache, or equals, contains or lies inside any adapter's credential path MUST be a configuration error (exit 2)
that names the key, never the path.

#### Scenario: SCN-SEC-79 (+) A setup gate reads the registry login, a test gate and an agent do not
- **GIVEN** `sandbox.setup_paths: ["~/.npmrc"]` and an existing `~/.npmrc`
- **WHEN** the argv of a setup gate, a test gate and an agent is built
- **THEN** only the setup gate's argv binds `~/.npmrc`, read-only

#### Scenario: SCN-SEC-80 (−) A tool path inside a login is refused
- **GIVEN** `sandbox.tool_paths: ["~/.codex/bin"]`
- **WHEN** the configuration is loaded
- **THEN** loading fails with exit 2 naming `sandbox.tool_paths`, and the message does not contain the path

#### Scenario: SCN-PRV-105 (+) Doctor warns while setup_paths is set
- **GIVEN** `sandbox.setup_paths: ["~/.npmrc"]`, with or without bwrap on the machine
- **WHEN** doctor runs
- **THEN** `SANDBOX-004` is reported as a warning that a registry login is in reach of setup code, the path is not echoed, and the exit code is unchanged; with `setup_paths: []` the row passes

### Requirement: L4-SEC-034 Every per-unit directory carries the repository key
Per-unit directories under `$L4_CACHE` SHALL include the repository key of L4-WTR-001: `units/<key>/<fw>/<name>` for
the step temp directories, `excludes`, the agents' raw streams and the merge-base checkout,
`pending-unpublished/<key>/<fw>/<name>`, and `{unit}` in `sandbox.caches` = `<key>/<fw>/<name>`. The harness MUST NOT
write or remove anything of the earlier layout, except that it moves a run file of it whose commits are in this
repository to the keyed directory and publishes it.

#### Scenario: SCN-SEC-81 (−) Two projects with the same unit name share no directory
- **GIVEN** two repositories with different `origin` URLs, one runner cache, and a unit `openspec:add-login` in each
- **WHEN** a workbench is built for each and project A resets its agent temp directory
- **THEN** the unit caches, `agent-tmp`, `gate-tmp`, `excludes` and every cache mount differ, and project B's result file is still there

#### Scenario: SCN-SEC-82 (−) A unit of another project is not handed this project's uv cache
- **GIVEN** project A's unit `add-login` that wrote a file into its uv cache
- **WHEN** project B's unit `add-login` mounts its caches
- **THEN** B's uv cache is new (it gets B's seed copy) and does not hold A's file

#### Scenario: SCN-SEC-83 (−) One project's unpublished run file never reaches another project's lock ref
- **GIVEN** project A kept an unpublished run file of `openspec:add-login`
- **WHEN** project B's run of `openspec:add-login` starts and publishes what is unpublished
- **THEN** B's unpublished files are empty and nothing is pushed for A's run

#### Scenario: SCN-SEC-84 (+) A run file of the earlier layout is adopted only by its own repository
- **GIVEN** two run files in `pending-unpublished/openspec/add-login`, one whose `run.started` names a commit of this repository and one whose commits are not here
- **WHEN** the run starts
- **THEN** the first is moved to the keyed directory and published, the second is left in place, and one warning names its directory

### Requirement: L4-SEC-035 Gates that do not build the environment cannot change it
A gate sandbox of a command other than `gates.setup` SHALL bind read-only each existing environment directory of the
tree it runs in (`.venv` at the root, every `node_modules` git tracks no file in), after the cache and git binds and
before the guidance masks; each `node_modules/.cache` and `node_modules/.vite` MUST be empty at the start of every such
gate (a tmpfs under bwrap). Setup gates and agent sandboxes keep them writable.

#### Scenario: SCN-SEC-85 (−) A test gate cannot write into the environment
- **GIVEN** a working bwrap and a worktree with `.venv/lib/python3.12/site-packages` and `node_modules/pkg`
- **WHEN** a test gate writes `zz.pth` into site-packages and changes `node_modules/pkg/index.js`
- **THEN** both writes fail, and a setup gate in the same worktree can write both

#### Scenario: SCN-SEC-86 (+) A uv project's tests run on the read-only environment setup built
- **GIVEN** a working bwrap, uv on PATH and a uv project with no dependencies
- **WHEN** the setup gate runs `uv sync --frozen` and the test gate runs `uv run --frozen python -c "print(1)"`
- **THEN** both gates pass and `.venv` was read-only in the test gate

#### Scenario: SCN-SEC-87 (+) The tool caches start empty and writable in every gate
- **GIVEN** a worktree whose `node_modules/.vite/deps` holds a file from an earlier gate
- **WHEN** the next test gate starts, under bwrap or under `sandbox.mode: none`
- **THEN** `node_modules/.vite` is an empty directory the gate can write, and under bwrap its argv has `--tmpfs` over it after the read-only bind of `node_modules`

### Requirement: L4-SEC-036 An environment an agent step or a gate changed is rebuilt
After each passing `gates.setup` command the harness SHALL record a manifest of the tree's environment directories
(lstat of every entry, ctime included). After every agent step and every other gate it MUST remove a directory that
differs, is new or has no manifest, so the next `gates.setup` builds it again, and record `env.rebuilt` and, per planted
path, a `guard.violation` (rule `environment`), or a non-failing `guard.notice` for a dependency upgrade with no lock file.

#### Scenario: SCN-SEC-88 (−) A `.pth` planted by a green step does not make green pass
- **GIVEN** a red task whose green step writes only `zz_l4.pth` and a pytest plugin that turns failures into passes into `.venv` site-packages, the production code left a stub
- **WHEN** the green phase runs
- **THEN** green fails on the stub, the plant is gone, and `guard.violation{rule: "environment"}` names `zz_l4.pth`

#### Scenario: SCN-SEC-89 (−) Plants that survive `uv sync --frozen` are removed by the harness
- **GIVEN** uv on PATH, a synced uv project, and `zz_planted.pth` and `sitecustomize.py` written into its site-packages after the manifest
- **WHEN** `uv sync --frozen` runs again, and then the harness compares the environment
- **THEN** both files survive the sync, the harness reports both as planted and removes `.venv`, and the next sync builds it without them

#### Scenario: SCN-SEC-90 (+) A dependency the agent declared is installed again with no violation
- **GIVEN** an agent step that changes `pyproject.toml` and `uv.lock` and adds a dist whose files its `RECORD` lists with their hashes
- **WHEN** the step ends
- **THEN** `env.rebuilt{declared: true}` is recorded, `.venv` is removed, and no `guard.violation` is recorded

#### Scenario: SCN-SEC-91 (−) Under `sandbox.mode: none` a gate's plant is removed after the gate
- **GIVEN** `sandbox.mode: none`, `sandbox.allow_none: true`, and a test gate whose test writes `sitecustomize.py` into `.venv`
- **WHEN** the gate ends
- **THEN** `.venv` is removed, `guard.violation{phase: "gate", rule: "environment"}` names the file, and `setup_at` is cleared, so no later gate runs on the planted environment: the next `run_setup` builds it again, and a gate before that runs without it and fails rather than passes

#### Scenario: SCN-SEC-92 (−) A changed installed package is removed with `node_modules`
- **GIVEN** an agent step that edits `node_modules/vitest/dist/index.js` and changes no package manifest or lock file
- **WHEN** the step ends
- **THEN** `node_modules` is removed, and `guard.violation` names `node_modules/vitest/dist/index.js`

#### Scenario: SCN-SEC-93 (−) An environment a gate created is not left for the next gate
- **GIVEN** `gates.setup: []` and a test gate whose command creates `.venv`
- **WHEN** the gate ends
- **THEN** `.venv` is removed with `env.rebuilt{reason: "created"}`

#### Scenario: SCN-PRV-106 (+) A dependency upgrade without a lock file is a notice, not a violation
- **GIVEN** a unit whose `package.json` has no dependency at HEAD, an installed `node_modules/vitest`, and a step that writes no lock file
- **WHEN** the step adds `vitest` to `dependencies` and changes `node_modules/vitest/dist/index.js`
- **THEN** `node_modules` is removed, `env.rebuilt{declared: false}` and one `guard.notice{rule: "environment"}` naming the file are recorded, and no `guard.violation` is

#### Scenario: SCN-PRV-107 (−) A startup hook is never excused by a manifest change
- **GIVEN** a step that adds a dependency to `pyproject.toml`, writes no lock file, and writes `zz.pth` into `.venv` site-packages
- **WHEN** the step ends
- **THEN** `.venv` is removed and a `guard.violation{rule: "environment"}` names `zz.pth`

### Requirement: L4-SEC-037 A workbench's gates run on an environment it built
The first `gates.setup` command a workbench runs in a tree SHALL first remove that tree's environment directories when
the workbench holds no manifest for it, so the verifier, a fix unit and any later workbench never run gates on an
environment an earlier step left. A run's first setup in a new worktree removes nothing.

#### Scenario: SCN-SEC-94 (−) The verifier never runs on the implementer's environment
- **GIVEN** a worktree whose `.venv` an implementer workbench built, with a file added to it after its manifest
- **WHEN** the verifier's workbench runs `gates.setup`
- **THEN** `.venv` is removed first with `env.rebuilt{reason: "unverified"}` and built again, without the file

#### Scenario: SCN-SEC-95 (+) The first setup in a fresh worktree removes nothing
- **GIVEN** a new worktree with no environment directory
- **WHEN** the implementer's first `gates.setup` runs
- **THEN** no `env.rebuilt` is recorded and the manifest is taken after the setup

### Requirement: L4-SEC-038 Doctor SANDBOX-003 proves the home and the runner cache are hidden
Doctor `SANDBOX-003` SHALL plant canaries (a file in `$HOME` outside every credential path, a credential file in another
unit's step directory, a lock file) and run them through the real gate and agent argv; a readable canary MUST fail the
check (exit 3) naming the path and the kind, never the content, and the canaries MUST be removed. It SHALL be skipped
when bwrap is absent or `sandbox.mode` is not `auto` or `bwrap`.

#### Scenario: SCN-SEC-96 (−) A readable canary fails the check
- **GIVEN** a fake runner whose agent sandbox reports the home canary readable
- **WHEN** `SANDBOX-003` runs
- **THEN** it fails naming the canary path and `agent`, prints no canary content, and no canary is left on disk

#### Scenario: SCN-SEC-97 (+) The real argv passes the check
- **GIVEN** a Linux runner with a working bwrap
- **WHEN** `l4 doctor` runs `SANDBOX-003`
- **THEN** it passes and no canary is left on disk

#### Scenario: SCN-SEC-98 (+) The check is skipped without a bwrap sandbox
- **GIVEN** `sandbox.mode: none` with `sandbox.allow_none: true`
- **WHEN** `SANDBOX-003` runs
- **THEN** it is skipped with a reason that names the mode

## MODIFIED Requirements

### Requirement: L4-SEC-005 Agent sandbox contents (part b)
Each agent run SHALL execute in its own sandbox with the real home and the runner cache covered by a tmpfs (L4-SEC-030,
L4-SEC-031), the tool paths read-only (L4-SEC-032), the worktree read-write, the shared `.git` directory read-only, a
private writable temp directory holding `$L4_RESULT_PATH`, only that profile's `sandbox.credential_paths` read-write, and
network allowed. Another profile's credential paths MUST NOT be present.

#### Scenario: SCN-SEC-10 (−) One profile cannot read another profile's login
- **GIVEN** `codex-sol` and `claude-sonnet` both with subscription logins on the runner
- **WHEN** code running inside the Codex agent sandbox reads `~/.claude/.credentials.json`
- **THEN** the file is not present in that sandbox; doctor `SANDBOX-001` verified this pairwise

### Requirement: L4-SEC-005 Gate sandbox contents (part c)
Every gate command, test, build, `serve` and scanner run on the worktree SHALL execute in a gate sandbox with the
worktree read-write, `.git` read-only, an empty home (L4-SEC-030: only the tool paths of L4-SEC-032 under it), the runner
cache hidden (L4-SEC-031), the environment read-only unless the command is `gates.setup` (L4-SEC-035), no credential
paths and no credential environment variables, and network allowed unless `gates.network: none`.

#### Scenario: SCN-SEC-N7 (−) Gate sandbox has no network when configured
- **GIVEN** `gates.network: none` and a test that opens a TCP connection to a public address
- **WHEN** the test gate runs
- **THEN** the connection fails inside the gate sandbox and the gate command line carries `--unshare-net`

### Requirement: L4-SEC-005 Caches and private home (part d)
Both sandbox kinds SHALL mount the per-unit cache directories of `sandbox.caches`, keyed by the repository key
(L4-SEC-034), with their environment variables, and `HOME` inside a sandbox MUST be a tmpfs over the real home holding
only the declared mounts (L4-SEC-030), so agent-written code can neither poison another unit's or project's cache nor
read the home.

#### Scenario: SCN-SEC-N8 (−) A cache write in unit A is invisible to unit B
- **GIVEN** units `a` and `b` with `uv` cache paths under `$L4_CACHE/units/{unit}/cache/uv`
- **WHEN** a gate in unit `a` writes a file into its `UV_CACHE_DIR`
- **THEN** the file is absent from unit `b`'s `UV_CACHE_DIR`
