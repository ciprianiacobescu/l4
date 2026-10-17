# Sandbox isolation: an empty home, a hidden runner cache, keyed unit directories, and no environment plants

Status: design, 2026-10-17. Harness at 0.4.14 (`795e97a9`). Markers: **[V]** verified (read at the cited line, or run),
**[I]** inferred from the code, **[U]** unknown until the named test or live check runs.

## 1. The findings in 0.4.14

| Finding | Still applies in 0.4.14 | Where |
|---|---|---|
| sandbox-security-2 (major): the real `$HOME` is visible | yes [V] | `sandbox/bwrap.py:68-73` (`base_flags` starts with `--ro-bind / /`, no cover of the home); `bwrap.py:109-110` hides only `hidden_credential_paths` (`sandbox/base.py:101-113`); `bwrap.py:17` lists "empty home" as pending; `docs/runner/README.md:259-263` says the same |
| implementer-2 (blocker): `.venv`/`node_modules` plants | yes [V] | `implementer/workbench.py:74` (`purge_bytecode` skips `.venv`, `node_modules`), `:384` (`git clean` keeps `HARNESS_EXCLUDES`), `implementer/tdd.py:1205` (the comment "`uv sync --frozen` removes what the agent installed" is false for a file no dist owns [V, uv 0.10.0: a `.pth` and a `sitecustomize.py` survive `uv sync --frozen` and `--reinstall`]); nothing under `src/l4` compares the environment |
| sandbox-security-1 (major): per-unit paths have no repository key | yes [V] | `workbench.py:566` (`cache / "units" / framework / ref.name`), `sandbox/caches.py:23-24` (`{unit}` = `<fw>/<name>`), `config/defaults.py:64-70`, `state/pending.py:88,96`, `orchestrator.py:1245,1275`, `state/restart.py:273`, `verifier/basemerge.py:66-67`, `implementer/uvseed.py:92`, `verifier/playwright.py:69` (follows `wb.unit_cache`) |
| sandbox-security-4 (major): another unit's key files are readable | yes [V] | `agents/opencode.py:207-218` (key file in `<agent-tmp>/opencode-config/provider.key`), `agents/credentials.py:104-111` (loader file in `<agent-tmp>/credential`); both under `$L4_CACHE/units/...`, which `--ro-bind / /` shows to every sandbox; no mask over `$L4_CACHE` in `bwrap.py:103-127` |

The same mounts also close sandbox-security-6 (minor) for the default layout: the login lock files live in
`~/.cache/l4/locks` (SPEC 8.4; `l4.agents.gate.lock_root`, the passwd home of the runner user) and the unit locks in
`$L4_CACHE/locks/<key>/...` (`UnitNames.flock_path`), both under a hidden root after this change. **Owner decision Q3: -6
is recorded as fixed by this change, on one condition that the tests carry**: SCN-SEC-99 shows, with the paths taken from
`lock_root` and `UnitNames` (never literals) and a model of the bwrap mount order (`tests/unit/sandbox/mountsim.py`),
that neither lock file is readable in a gate or an agent sandbox of any adapter (the login lock directory lies under no
adapter's credential path, so the agent kind's bind of its own login does not bring it back), with the cache under the
home and outside it; and, where bwrap exists, by a real read in both kinds. Two limits are stated, not hidden: a
`$L4_LOCK_DIR` outside the home and the cache stays readable (an operator's choice, named in the runbook), and under
`sandbox.mode: none` nothing is hidden. The other half of -6, that a read-only descriptor is enough for `flock`, is not
changed here: the files are no longer reachable.

## 2. Goals and non-goals

Goals: the SPEC's own words hold for bwrap ("an empty home", L4-SEC-005; SANDBOX-001's "no git credential"); nothing
outside the committed tree that an agent or a gate can write reaches a gate that decides a verdict; per-unit state of
two projects never meets; a key file is readable only in the sandbox of its own step.

Non-goals: `mode: user` and `mode: container` (still M2: when built they must meet L4-SEC-030..033 by their own means);
the full SANDBOX-001 (per-profile pairwise probes, ancestor environment; sandbox-security 1.12-1.13 stay open);
poisoning of a unit's **own** package cache by its own agent-written code (residual R3, open question Q2); the other
review findings (implementer-1, -3, sandbox-security-3, -5, -6).

## 3. Decisions

### D1. The home: a tmpfs over the real home, `HOME` keeps its path (L4-SEC-030)

Chosen: `--tmpfs <spec.home>` right after `base_flags`, then explicit binds. Rejected: a private `HOME` under the step's
temp directory. The CLIs find their logins at `~/.claude`, `~/.codex`, `~/.local/share/opencode`, and shims and venvs
carry absolute paths into the real home (`#!/home/u/.local/share/uv/tools/serena/bin/python`), so the real paths must
exist inside anyway; a second home only adds a remapping. `gate-tmp` also lives across gates and runs, so a home there
would be a channel between gates; the tmpfs dies with the sandbox. `HOME` in the child environment stays `spec.home`
(`sandbox/env.py:22`, unchanged): inside, it is an empty writable tmpfs plus the binds below.

`spec.home` that is not absolute, is `/`, or is not an existing directory raises `SandboxUnavailable` (exit 3) in
`BwrapSandbox.build_argv`: a `HOME` that names nothing does not mean the user's files are elsewhere-safe, it means the
harness does not know where they are (fail closed).

### D2. The runner cache: a second tmpfs (L4-SEC-031)

`SandboxSpec` gets a required keyword field `cache_root: Path` (`cache_root(environ, repo=...)`). `build_argv` emits
`--tmpfs <cache_root>` after the home's tmpfs when the cache root is an existing directory, is not `/` and is not inside
`spec.home` (inside the home it is already covered). Everything the step needs under it (`spec.worktree`,
`spec.tmp_dir`, each `CacheMount`, a tool path under it) is bound after it; bwrap creates the mount points inside the
tmpfs [V bwrap semantics; the binds of the worktree under `/tmp` work the same way today]. This hides every other
unit's and project's `agent-tmp`, `gate-tmp`, `agent-raw`, worktrees, `pending-unpublished`, the seed and the unit lock
files, and the hello probe's `l4-opencode-probe-*` directory (`services.py:137`: the probe's cwd is the cache root).
The reviewer's narrower `--tmpfs <cache_root>/units` is rejected: it leaves the worktrees and locks visible.

### D3. The argv order (both kinds)

```
bwrap <base_flags: --ro-bind / /, --dev, --proc, --tmpfs /tmp, /run masks, --unshare-*, --die-with-parent>
  --tmpfs <home>                                   D1
  --tmpfs <cache_root>                             D2 (when outside the home)
  --ro-bind <p> <p>   for p in spec.tool_paths     D4 (sorted; a path inside an earlier one is skipped)
  --ro-bind <p> <p>   for p in spec.setup_paths    D5 (gate of a setup command only)
  <hide> other adapters' credential paths          existing, moved after the tool binds: no tool bind re-exposes a login
  <hide> spec.runner_tmp                           existing
  --bind <own credential paths>                    agent kind only, existing
  --bind <worktree>  --bind <tmp_dir>              existing
  <cache mounts>                                   existing
  --ro-bind <git_common_dir>                       existing
  --ro-bind <d> <d>   for d in spec.read_only      D6 (gate of a non-setup command)
  --tmpfs <d>         for d in spec.empty_dirs     D6 (the tool caches inside those)
  --tmpfs <guidance dirs>                          existing, still last (HB-X1)
  --clearenv --setenv ... --chdir ... -- argv
```

`hidden_credential_paths` keeps its host-existence rule (`_hide`); under the home's tmpfs a mask over a path that no
bind put back only creates an empty mount point there, which is harmless and keeps one rule for both cases. The probe's
`m0_argv` (`scripts/runner/sandbox-probe.sh`) builds the same order; the parity test passes the Python-derived
`tool_paths` and `cache_root` to it as `tool:DIR` and `root:DIR` arguments, so the derivation (D4) is Python-only and the
argv shape is checked in both.

### D4. Which tools come back (L4-SEC-032), and why not "bind each PATH entry" alone

A new module `src/l4/sandbox/home.py` owns one function, `tool_paths(host_env, *, home, cache_root, kind, configured,
forbid) -> tuple[Path, ...]`, the only source of `SandboxSpec.tool_paths`. A **hidden root** is `home` or `cache_root`.
The result is every existing path below, that lies under a hidden root, is not inside `forbid` (the worktree and the
main checkout, as `safe_path` forbids them), in this order, deduplicated (a path inside an earlier one is dropped):

1. each entry of `safe_path(host_env, forbid=forbid)` (the PATH the sandbox gets, `sandbox/env.py:21`), and its resolved
   path when the entry is a symlink;
2. for an entry ending in `node_modules/.bin`, its `node_modules` directory (a `.bin` shim points into a sibling package;
   pnpm set up by `pnpm/action-setup` lives in `~/setup-pnpm/node_modules`);
3. for each symlink directly inside an entry of 1 whose resolved target is a regular file under a hidden root and
   outside that entry, its install root: the parent of the outermost `node_modules` on the target's path when there is
   one (an npm global install, nvm's `npm`), else the target's parent directory (Claude's native install
   `~/.local/share/claude/versions/<v>`, a uv tool's `bin`);
4. `l4_home(host_env)` (`$L4_HOME`, default `~/.local/share/l4`: node, the npm prefix with the agent CLIs, Laya);
5. uv's Python and tool directories: `$UV_PYTHON_INSTALL_DIR` else `<data>/uv/python`, `$UV_TOOL_DIR` else
   `<data>/uv/tools`, `<data>` being `$XDG_DATA_HOME` else `~/.local/share` (a `.venv/bin/python` of a uv-managed
   interpreter resolves there; serena and the harness itself may be uv tools). Not `<data>/uv` as a whole: uv keeps
   `credentials/` there;
6. the corepack home: `$COREPACK_HOME` else `~/.cache/node/corepack` (a corepack-enabled pnpm or yarn is downloaded
   there; without it a gate with `gates.network: none` cannot start pnpm);
7. the harness's own gate plugin directories, `l4.gates.trace.plugin_dir()` and `l4.gates.coverage.plugin_dir()`: they
   reach every test gate through `PYTHONPATH` (`gates/trace.py:22`, `gates/coverage.py:91`), and a harness run by `uvx`
   lives in `~/.cache/uv/archive-v0/...`, which the home's tmpfs would otherwise hide from every test gate;
8. agent kind only: `~/.serena` (Serena's global config and downloaded language servers), read-only as it is today
   under `--ro-bind / /`, where Serena already starts with it read-only [I: no bind makes it writable in 0.4.14];
9. `sandbox.tool_paths` (D5).

Then the other adapters' credential masks follow (D3), so a tool path that holds a login (say a PATH entry
`~/.local/share/opencode/bin`) still hides it. Rejected: binding only the PATH entries (breaks npm's sibling packages,
nvm's `npm`, a uv venv's interpreter, the trace plugin under the uvx cache); binding the parent prefix of every `bin`
entry (turns `~/.local/bin` into all of `~/.local`, with `share/` and `state/` of every other program).

Residual [U]: a tool under the home that none of 1-8 reaches fails inside the sandbox ("command not found", a broken
venv). The fix is a `sandbox.tool_paths` entry; the live check (task 7.1) runs the dummy repository's gates and one agent
of each adapter on `l4-runner` and on a GitHub-hosted runner before release.

### D5. Two new keys, validated at load (L4-SEC-033)

```yaml
sandbox:
  tool_paths: []     # ~/... or absolute; read-only into both kinds (a tool under the home that D4 does not find)
  setup_paths: []    # ~/... or absolute; read-only only into the gate sandbox of a gates.setup command (~/.npmrc,
                     # ~/.config/pip/pip.conf, ~/.netrc for a private registry or a git dependency)
```

`SandboxCfg` (`config/schema.py:281`) validates each entry like `credential_paths` (`~/` or absolute), and refuses (a
`ValueFree` error, exit 2 at load, naming the key and never the path) an entry that is `/` or `~`, or that equals,
contains or lies inside any adapter's credential path, built-in or configured (compared as `~/`-expanded text against a
placeholder home, so no environment is needed). The checks that need the environment, an entry that contains the
runner cache and an absolute entry that overlaps a credential path once `~` is expanded, are made where the paths are
expanded: `l4.sandbox.home.tool_paths()` and `home.setup_paths()` raise `L4Exit(USAGE_ERROR)` naming the key, at the
first sandbox spec of the run.
Why `setup_paths` exists: today a setup gate reads `~/.npmrc` through `--ro-bind / /`; the empty home would break a
consumer with a private registry and leave only `sandbox.mode: none`. It is setup-only because setup is the one gate
that downloads; code an agent influences still runs there (a build hook, a `postinstall` script), which is residual R2.

### D6. The project environment is read-only for gates that do not build it (L4-SEC-035)

New module `src/l4/sandbox/envdirs.py` (sandbox layer, no implementer imports):

- `ENV_DIR_NAMES = (".venv", "node_modules")`, `TOOL_CACHE_DIRS = (".cache", ".vite")`;
- `env_dirs(tree: Path, tracked: Collection[str] = ()) -> list[Path]`: `.venv` at the tree root, and every directory
  named `node_modules` found by walking the tree (not descending into `.git`, `.venv`, a `node_modules`, `.l4-out` or a
  symlinked directory). A directory git tracks a file in (`tracked`, from `git ls-files -z -- .venv node_modules
  '**/node_modules/**'`) is source, not an environment, and is left out. A symlink named like an environment directory
  is returned (D7 removes it), never mounted;
- `read_only_mounts(tree, tracked) -> tuple[tuple[Path, ...], tuple[Path, ...]]`: (the real directories of
  `env_dirs`, the `TOOL_CACHE_DIRS` that exist as real directories inside each `node_modules`).

`gate_sandbox_spec(..., builds_env: bool)` (a required keyword) fills `SandboxSpec.read_only` and
`SandboxSpec.empty_dirs` from `read_only_mounts` when `builds_env` is false, and `SandboxSpec.setup_paths` from
`sandbox.setup_paths` when it is true. `Workbench.gate_spec(..., builds_env=False)` passes it through. Every caller that
runs a `gates.setup` command passes `builds_env=True`: `tdd.run_setup`, `verifier/gates.run_build_gates` (name
`setup`), `uvseed._fill`, `verifier/playwright.base_checkout` (`setup-base`), `gates/dryrun.py` (gate `setup`),
`yolo/postcheck.py` (its setup items). Default false is fail-safe: a forgotten setup caller fails with a read-only
error, it never writes an environment a later gate trusts.

Tool caches: before every non-setup gate, `Workbench.run_gate_spec` calls `envdirs.reset_tool_caches(tree)`, which makes
each `node_modules/.cache` and `node_modules/.vite` an empty real directory (a symlink is unlinked first). Under bwrap
the `--tmpfs` over them needs the mount point to exist (a read-only parent cannot get a new directory), and under
`mode: none` the reset is the whole protection: `.vite/deps` holds pre-bundled modules that vite and vitest load [I].

Agent sandboxes keep both directories writable: a legitimate `uv add` or `npm install` must work, and D7 rebuilds.

[U] `uv run` against a read-only `.venv` under bwrap (EROFS): with `chmod -R a-w .venv` (EACCES) uv 0.10.0 ran `uv run
--frozen python` and plain `uv run python` with exit 0 [V, run 2026-10-17 on this mac]; SCN-SEC-86 runs it under real
bwrap. If it fails there, the fallback is to bind an empty writable file from the step's tmp over `.venv/.lock`.

### D7. Manifest, compare, rebuild (L4-SEC-036, L4-SEC-037)

New module `src/l4/implementer/envguard.py`:

- `Entry(kind, mode, size, mtime_ns, ctime_ns, ino, target)` from `os.lstat`; `EnvManifest = dict[str, Entry]` keyed by
  the path relative to the tree; `take_manifest(tree, tracked) -> EnvManifest` walks every `envdirs.env_dirs` entry
  without following symlinks and skips `TOOL_CACHE_DIRS` subtrees. ctime is the tamper evidence: a same-uid process
  can reset mtime with `utime`, never ctime; a replacement by rename changes `ino` [V POSIX; macOS `st_ctime_ns` exists].
  No content hashing: an lstat walk of a 50,000-file `node_modules` is well under a second [I].
- `diff_manifest(before, after) -> EnvDiff(added, changed, removed)` (sorted relative paths).
- `planted(tree, diff, changed_files) -> list[str]`, used for reporting only (the rebuild, not the classification, is the
  protection; an agent can also rewrite a `RECORD`). A path is planted when it was added or changed and:
  - its name is `*.pth`, `sitecustomize.py`, `usercustomize.py` or `*.pyc` and the install was not declared or no
    `*.dist-info/RECORD` lists it with a matching sha256; or
  - it is under `.venv` and no `RECORD` of the current environment lists it with a matching sha256 (paths in `RECORD` are
    relative to their site-packages directory; `../../../bin/x` resolves to `.venv/bin/x`); or
  - it is under a `node_modules` and the install was not declared.
  The install is **declared** when `changed_files` (the step's `Workbench.changed_files()`) holds a dependency manifest
  or lock file at any depth: `pyproject.toml`, `uv.lock`, `poetry.lock`, `Pipfile.lock`, `setup.py`, `setup.cfg`,
  `requirements*.txt`, `package.json`, `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock`,
  `bun.lock`, `bun.lockb` [V for the RECORD shape: uv writes `path,sha256=<b64>,size` for every installed file;
  `__pycache__/*.pyc` and `_virtualenv.pth` are in no RECORD, so they must be in the manifest from setup, which they are].
- `remove_env_dir(path)`: `unlink` for a symlink, else `shutil.rmtree`.

`Workbench` gets `env_manifests: dict[Path, EnvManifest]` (in memory only: a file under the cache would be one more thing
`mode: none` code could edit) and:

- `run_gate_spec(..., builds_env=False)`: before the run, a setup gate (`builds_env`) in a tree the workbench holds no
  manifest for removes that tree's environment directories (`env.rebuilt{reason: "unverified"}` when any existed): this
  is L4-SEC-037, so a verifier's workbench, a fix unit's and one rebuilt after a fallback (`orchestrator.py:995,1013`)
  never start on an environment an earlier step left; a run's first setup in its fresh worktree
  (`WorktreeManager._remove` at run start, `vcs/worktree.py:232-244`) finds nothing to remove. A non-setup gate first
  calls `reset_tool_caches`. After a passing setup gate the manifest of that tree is taken (after `reset_tool_caches`);
  after any other gate, `check_env(tree, phase="gate")`.
- `check_env(tree, *, phase, changed=()) -> bool`: no environment and no manifest → nothing. Otherwise, per environment
  directory, compare with the manifest; a directory that differs, is new, or has no manifest is removed, its entries
  dropped from the manifest, `setup_at` set to `None` when `tree` is the worktree, and recorded:
  `env.rebuilt{tree, dirs, phase, added, changed, removed, reason: changed|created|unverified, declared}` once, and one
  `guard.violation{path, rule: "environment", action: "removed", phase}` per planted path, at most 20 (the count of the
  rest in `env.rebuilt.planted_more`). Returns whether anything was removed.
- `tdd.agent_step` calls `wb.check_env(wb.worktree, phase=role, changed=wb.changed_files())` in its `finally`, after
  `revert_protected` and `restore_ledger` (`tdd.py:708-717`). `setup_at = None` is already set there, so the next
  `run_setup` (every gate path after an agent step calls it: `tdd.py:516, 828, 851, 1125, 1177, 1205, 1290, 1623, 1652`)
  builds the environment again from the working tree's lock files.
- `guardnotes._ADVICE["environment"]`: "The harness rebuilds `.venv` and `node_modules` from the lock files after every
  step and removed what the step wrote there. Declare a dependency in the manifest and the lock file (`uv add`, `npm
  install` are fine); never write into an installed environment."
- The comment at `tdd.py:1205` becomes true: "`gates.setup` runs on an environment the harness rebuilt after the agent
  step (L4-SEC-036)".

`run_gate_spec` does not call `run_setup` itself (a gate does not start another gate). In a sequence of gates with no
`run_setup` between them (the static gates after green's test gate, the verifier's setup, build, lint, typecheck,
repository-ci loop), a gate after a removal runs with no environment and fails: fail-safe, never a pass on the plant.
Under bwrap this needs a plant by a gate, which the read-only binds prevent; it is a `mode: none` path.

A project with `gates.setup: []` never gets a manifest: every environment directory an agent step or a gate leaves is
removed (`unverified` / `created`), so a test command that builds its own (`uv run`) builds it in every gate. Correct, and
slow; the runbook says to set `gates.setup`.

Why not the reviewer's "sweep site-packages after setup": setup itself writes files no `RECORD` lists (`_virtualenv.pth`,
`_virtualenv.py`, the reviewer's own `_host.pth`) [V], so a sweep needs an allow-list of installer files, and it still
misses an edited RECORD-listed file (`_pytest/runner.py`). The manifest needs neither.

### D8. Repository key in every per-unit path (L4-SEC-034)

- `vcs/names.py`: a function `unit_dir(cache: Path, repo_key: str, unit_id: str) -> Path` =
  `cache / "units" / repo_key / fw / name`; `UnitNames` gains `repo_key`, `unit_cache` (that path) and
  `unpublished_dir` (`cache / UNPUBLISHED_DIR / repo_key / fw / name`).
- `make_workbench` (`workbench.py:557-567`) computes the key from the git common dir it already reads
  (`repokey.key_of_common_dir(common, app.environ)`, the function `repository_key` calls) and stores `cache_root` and
  `repo_key` on the `Workbench`; `unit_cache = unit_dir(...)`.
- `sandbox/caches.py`: `mount_caches(caches, cache_root, unit_id, repo_key)`; `{unit}` expands to
  `<repo_key>/<fw>/<name>`. Keeping the placeholder (rather than a new `{repo}`) keys every existing configuration with
  no edit; the SPEC defaults keep their text. Callers: `make_workbench`, `verifier/fixloop.py:307`, `gates/dryrun.py:231`,
  `yolo/postcheck.py:172` (each has a git or `app.repo` to key from).
- `uvseed._seed_and_copy` uses `wb.cache_root` instead of `wb.unit_cache.parent.parent.parent` (`uvseed.py:92`).
- `verifier/basemerge._excludes` uses `ctx.services.names.unit_cache / "excludes"` (`basemerge.py:66-67`).
- `state/pending.py`: `keep_unpublished(directory, run_file)` and `unpublished_files(directory)` take the keyed directory;
  `orchestrator.py:1245,1275` pass `s.names.unpublished_dir`; `state/restart.py:273` removes the keyed one.
- Migration of `pending-unpublished/<fw>/<name>` (the earlier layout): `pending.adopt_legacy(legacy_dir, keyed_dir, git)`
  runs before `_publish_unpublished`; a legacy `<run-id>.jsonl` whose `run.started` names a commit (its base or head) that
  `git cat-file -e` finds in this repository is moved into the keyed directory and published as usual; any other is left
  in place and named in one warning line per run (`[l4] <n> unpublished run files of the earlier layout in <dir> belong
  to no commit of this repository; they are kept and never published`). A wrong adoption needs another project with the
  same unit name whose run recorded a commit of this repository: a fork, which shares the history it would be published
  into [I]. Everything else of the earlier layout (`units/<fw>/<name>`) is never read, written or removed (as
  L4-WTR-001 does for the earlier lock paths); a new keyed uv cache is new, so it gets the project's seed copy.

### D9. Key and credential files (L4-PRV-040, L4-PRV-041)

The mounts of D2 are what make them private: the step's `agent-tmp` is bound only into its own agent sandbox, and the
cache root is a tmpfs everywhere else. In addition: `Workbench.reset_agent_tmp` creates `agent-tmp` with mode 0700 and
`opencode.py` creates `opencode-config` with 0700 (`credentials.py` and `opencode_provider.py` keep `O_EXCL|O_NOFOLLOW`,
0600); the unit's `units/<key>/<fw>/<name>` directory is created 0700. `Workbench.__post_init__` removes a
`agent-tmp/opencode-config/provider.key` and an `agent-tmp/credential` left by a killed run (SIGKILL skips the `finally`
at `opencode.py:233-235`) before any agent or gate. The hello probe keeps its key in a `tempfile.TemporaryDirectory`
(0700 by `tempfile`) under its `ProbeCtx.cwd` [V `opencode.py:398-403`]: the cache root in a run (`services.py:137`,
hidden by D2), a scratch directory from `tempfile` in doctor and `l4 probe` (`doctor/checks_agents.py:43`,
`availability/fallback.py:611`; the system temp directory, which every sandbox replaces with its own `/tmp`).
Residual (unchanged, L4-SEC-005 part h): code an agent runs in its own sandbox can read its own key.

### D10. Doctor `SANDBOX-003` (L4-SEC-038)

In `doctor/checks_sandbox.py`, registered like SANDBOX-002 (severity error, skipped when bwrap is absent or
`sandbox.mode` is not `auto`/`bwrap`). It builds a probe worktree, temp dir and git dir under
`<cache_root>/doctor/sandbox-003-<hex>/`, one gate spec through `gate_sandbox_spec(builds_env=False)` and one agent spec
for the adapter of the first `roles.implementer` profile, with the real `tool_paths` and `cache_root`, plants three
canaries (`$HOME/.l4-canary-<hex>`, `<cache_root>/units/l4-canary-<hex>/x/y/agent-tmp/credential`,
`<cache_root>/locks/l4-canary-<hex>.lock`), runs `/bin/sh -c 'for f; do [ -r "$f" ] && echo "L4-READ:$f"; done; echo
L4-CANARY-DONE'` through `BwrapSandbox.wrap` in each kind, and removes the canaries and the probe directory in a
`finally`. A readable canary fails (exit 3) with the path and the kind; a probe that does not print the done marker fails
with its last stderr line. It never prints a canary's content (the canaries hold a random marker only). It is the live
half of the regression tests on a real runner; SANDBOX-001 stays as specified and unbuilt.

## 4. What changes where

| | GitHub-hosted runner (bwrap) | Self-hosted runner `l4-runner` (bwrap, gitlab-runner shell) | Mac with `sandbox.mode: none` (accepted risk) |
|---|---|---|---|
| Home | `/home/runner` holds the checkout (`~/work/<r>/<r>`), `RUNNER_TEMP` (`~/work/_temp`) and the default `~/.cache/l4` [I, the hosted image's layout]: all hidden but the step's binds. Tools are mostly in `/opt/hostedtoolcache` (outside the home, unchanged); uv, `$L4_HOME` and the agent CLIs come back by D4 | `/home/gitlab-runner` holds `builds/` of every project on the runner, `.ssh`, `.gitconfig` and the user-local tools: other projects' checkouts and every login file are hidden; tools come back by D4 | no mount: agents and gates still read the home (the accepted risk; the runbook says so) |
| Runner cache | under the home by default: covered by D1 | `$L4_CACHE` if set outside the home: covered by D2 | no mount |
| Keyed unit directories | yes | yes | yes |
| Environment read-only in gates | yes | yes | no mount: the manifest check after every gate is the only guard |
| Manifest and rebuild | yes | yes | yes (the main protection against plants here) |
| Key files | hidden from other sandboxes | hidden | 0700/0600 and removal only; same-uid code can still read them |
| `SANDBOX-003` | runs, fails closed | runs, fails closed | skipped with the reason |

## 5. Risks

- R1 [U] A tool D4 does not find: gates or agents fail after the upgrade. Mitigation: `sandbox.tool_paths`, the runbook
  line, the live check of task 7.1 on both runner kinds before release.
- R2 Residual: setup gates still run code the agent influences (a build backend hook, a `postinstall` script of the
  root `package.json`) with the environment writable and `sandbox.setup_paths` readable. The manifest is taken after it,
  so a plant made by setup itself is trusted. The hook is in the unit's diff (it is committed code), unlike a file in
  `.venv`.
- R3 Residual: a unit's own uv/pip/npm/pnpm cache stays writable for its agent and its gates; a poisoned cache entry would
  be copied into a rebuilt environment. Cross-unit and cross-project poisoning is closed by D8 and the per-unit caches.
  Open question Q2.
- R4 [U] `uv run` with a read-only `.venv` under bwrap (D6); a JS tool that writes inside `node_modules` other than
  `.cache`/`.vite` (`prisma generate` in a test gate) fails read-only and must move to `gates.setup`.
- R5 A CI builds directory outside the home (a custom `builds_dir`) stays readable; `runner_tmp_paths` still hides the
  own project's `.tmp`. Git alternates under the home need a `sandbox.tool_paths` entry.
- R6 Cost: an environment the agent changed is rebuilt (from a warm cache: seconds to a minute); the verifier rebuilds
  once per round.

## 6. Open questions for the owner

- Q1: `sandbox.setup_paths` hands a registry login to code the agent can influence during setup (R2). Keep the key, or
  require such projects to stay on `sandbox.mode: none`?
- Q2: close R3 in a follow-up by mounting the caches read-only in agent and test-gate sandboxes (the agent gets a private
  scratch cache for its own `uv add`), or by giving the verifier a fresh copy of the project seed as its uv cache?
- Q3: record sandbox-security-6 as fixed by this change (the lock directories are under hidden roots), or keep its own
  change for a hidden lock directory under `mode: none`?
- Q4: a rebuilt environment after a legitimate dependency change by the agent is reported as `env.rebuilt` only; an
  upgrade of a Node dependency without a lock change is reported as a `guard.violation`. Acceptable noise?
