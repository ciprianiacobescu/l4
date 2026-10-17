Every task follows these rules:
- Write the named tests first and see them fail on the unchanged code, then write the code. A test ported from the
  review keeps the reviewer's reproduction steps (the source is named; the reproductions live in the review scratchpad
  `.../scratchpad/l4review/`, and each task below restates what to build, so the test does not depend on that folder).
- Live bwrap tests use the helper `tests/unit/sandbox/bwrap_live.py` (task 2.1): `requires_bwrap` skips unless
  `sys.platform == "linux"`, `bwrap` is on PATH and `BwrapSandbox(exe).available().ok`. Their fake home and fake runner
  cache are made under `/var/tmp` (never under `/tmp`: every sandbox already covers `/tmp` with a tmpfs, so a canary
  there passes before the fix) and removed afterwards; they never write into the real home.
- uv tests skip when `uv` is not on PATH, and run uv with `UV_OFFLINE=1` and a `UV_CACHE_DIR` under `tmp_path`.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only. Never change git config.
- Run the groups in order: they share `implementer/workbench.py`, `sandbox/base.py` and `sandbox/bwrap.py`. An existing
  test whose expected argv or path layout changes is updated to the new behaviour, never deleted or weakened; the commit
  message names it.

## 1. Repository key in every per-unit path (sandbox-security-1; L4-SEC-034)

- [ ] 1.1 Tests, ported from `verify-sandbox-security/r1_unitcache_real.py`, in `tests/unit/sandbox/test_unit_dirs_keyed.py`.
  Build two git repositories under `tmp_path` (origins `https://gitlab.example.com/team-a/projecta.git` and
  `https://gitlab.example.com/team-b/projectb.git`, each with `openspec/changes/add-login/proposal.md` committed), one
  `L4_CACHE`, `HOME` under `tmp_path`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, and call the real
  `make_workbench(cfg=L4Config(), ..., sandbox=NoSandbox(allow_none=True), selected=None, iteration=1)` for each, as the
  reproduction does.
  - `test_two_projects_with_the_same_unit_share_no_directory` (SCN-SEC-81): `unit_cache`, `agent_tmp`,
    `unit_cache / "gate-tmp"`, `excludes` and every `CacheMount.path` differ between A and B, and each contains its
    project's `repository_key` as a path part; after B writes `agent-tmp/result.json` and A calls `reset_agent_tmp()`,
    B's file still exists and A's `result.json` is not what B reads.
  - `test_another_projects_uv_cache_is_new` (SCN-SEC-82): A writes `poisoned-wheel.whl` into its `UV_CACHE_DIR`; B's
    `UV_CACHE_DIR` is `l4.sandbox.seed.is_new(...)` and does not hold the file.
  - `test_the_unit_placeholder_carries_the_key`: `mount_caches(L4Config().sandbox.caches, root, "openspec:add-x",
    repo_key="proj-0123456789")` gives `root/units/proj-0123456789/openspec/add-x/cache/uv`; a configured
    `$L4_CACHE/custom/{unit}/npm` gives `root/custom/proj-0123456789/openspec/add-x/npm`; the read-only `playwright`
    cache is unchanged.
- [ ] 1.2 Code: `src/l4/vcs/names.py`: `unit_dir(cache, repo_key, unit_id) -> Path` (`cache/units/<key>/<fw>/<name>`),
  and `UnitNames` fields `repo_key`, `unit_cache` (that path), `unpublished_dir`
  (`cache/pending-unpublished/<key>/<fw>/<name>`, using `l4.state.pending.UNPUBLISHED_DIR`'s value without importing
  the state package if that makes a cycle: move the constant to `vcs/names.py` and re-export it from `pending.py`).
  `src/l4/sandbox/caches.py`: `mount_caches(caches, cache_root, unit_id, repo_key)`, `{unit}` = `<key>/<fw>/<name>`.
  `src/l4/implementer/workbench.py`: `make_workbench` computes `repo_key = key_of_common_dir(common, app.environ)`
  (`l4.vcs.repokey`; `common` is already read at line 559), adds `Workbench` fields `cache_root: Path` and
  `repo_key: str`, sets `unit_cache = unit_dir(...)` and creates it with mode 0700. `src/l4/implementer/uvseed.py:92`
  uses `wb.cache_root`. `src/l4/verifier/basemerge.py:66-67` uses `ctx.services.names.unit_cache / "excludes"`.
  The other `mount_caches` callers pass the key: `src/l4/verifier/fixloop.py:307` (`s.names.repo_key`),
  `src/l4/gates/dryrun.py:231` and `src/l4/yolo/postcheck.py:172` (`key_of_common_dir` of the `common` they read). Update
  `tests/unit/sandbox/test_caches.py` and any test that spells `units/<fw>/<name>` to the keyed layout.
  Verify: the 1.1 file, `tests/unit/sandbox/`, `tests/unit/implementer/test_setup.py`, `tests/unit/verifier/`.
- [ ] 1.3 Tests in `tests/unit/state/test_pending_keyed.py` (the reproduction's "extra" part):
  - `test_another_projects_unpublished_file_is_not_published` (SCN-SEC-83): `keep_unpublished(names_a.unpublished_dir,
    run_file)` for project A; `unpublished_files(names_b.unpublished_dir)` is `{}`; and `Orchestrator._unpublished`
    reads `services.names.unpublished_dir` (call it on an orchestrator built by the existing orchestrator test world in
    `tests/unit/orchestrator/`, or assert on a minimal fake `services` if that world cannot be pointed at two projects).
  - `test_a_legacy_run_file_is_adopted_only_by_its_repository` (SCN-SEC-84): in `<cache>/pending-unpublished/openspec/
    add-login/` put `r-20261017T1200Z-aaaa.jsonl` whose first line is a `run.started` naming this repository's HEAD sha
    (in the fields `run.started` really carries: read `LedgerWriter.open` and its caller for the base/head keys) and
    `r-20261017T1201Z-bbbb.jsonl` naming a sha that is not in the repository; `adopt_legacy(legacy_dir, keyed_dir, git)`
    moves the first into `keyed_dir`, leaves the second, and logs exactly one warning (caplog) naming `legacy_dir` and
    the count 1, never a file's content.
- [ ] 1.4 Code: `src/l4/state/pending.py`: `keep_unpublished(directory, run_file)`, `unpublished_files(directory)`,
  `adopt_legacy(legacy_dir, keyed_dir, git) -> list[Path]` (a file is adopted when a commit sha of its `run.started`
  passes `git cat-file -e <sha>^{commit}`; unreadable or unknown: left). `src/l4/orchestrator.py`: `_unpublished` and
  `_publish_pending` pass `s.names.unpublished_dir` (lines 1245, 1275); `_publish_unpublished` first adopts from
  `cache_root(...) / UNPUBLISHED_DIR / fw / name` and prints the one warning of design D8 when files are left.
  `src/l4/state/restart.py:273` removes `names.unpublished_dir` (and never the legacy directory). Verify: the 1.3 file,
  `tests/unit/state/test_pending.py`, `tests/unit/state/test_restart.py`, `tests/unit/orchestrator/`.

## 2. Hidden home and runner cache, tools read-only (sandbox-security-2, -4; L4-SEC-030..033)

- [ ] 2.1 Live tests, ported from `verify-sandbox-security/live_bwrap.py` parts `r2` and `r4` (run there as user
  `runner` in a privileged Debian 12 container, bwrap 0.8.0). Add `tests/unit/sandbox/bwrap_live.py` (`requires_bwrap`;
  a fixture `var_tmp_dir` that makes and removes a directory under `/var/tmp`, skipping when `/var/tmp` is not
  writable). In `tests/unit/sandbox/test_bwrap_live_home.py`, all `@requires_bwrap`, with a fake home `H` under
  `/var/tmp` and host env `{"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": H, "USER": ..., "LANG": "C.UTF-8",
  "GIT_CONFIG_NOSYSTEM": "1", git author/committer variables}`, a repository `H/proj` (origin
  `https://gitlab.example.com/g/proj.git`, units `add-login` and `add-search`), workbenches built by the real
  `make_workbench` with `BwrapSandbox(shutil.which("bwrap"))` and `selected=SimpleNamespace(profile=SimpleNamespace(
  adapter=...))` as in the reproduction, and every argv from `wb.gate_spec(network=True)` / `wb.agent_spec()` +
  `build_gate_env` / `build_agent_env` + `BwrapSandbox.wrap`, run with the reproduction's `READ` loop:
  - `test_a_gate_reads_no_credential_of_the_home` (SCN-SEC-70): `H` holds `.git-credentials`, `.netrc`,
    `.ssh/id_ed25519`, `.config/gh/hosts.yml`, `.docker/config.json` (the reproduction's values, mode 0600) and
    `.codex/auth.json`; unit B's (claude-code) gate reads none of them. `L4_CACHE` unset, so the cache is `H/.cache/l4`.
  - `test_an_agent_sees_its_own_login_and_nothing_else` (SCN-SEC-71): add `H/.claude.json`; B's agent sandbox reads only
    it.
  - `test_another_units_step_files_and_locks_are_hidden` (SCN-SEC-75): `L4_CACHE` = a second `/var/tmp` directory
    outside `H`; a file in unit A's `agent-tmp`, a file in `worktrees/other-0123456789/openspec/x/` and a file in
    `locks/`; B's gate and agent read none, and do read a file in B's own worktree and in B's uv cache.
  - `test_tools_under_the_home_run_in_both_kinds` (SCN-SEC-78): `H/.local/bin/l4-tool-a` (`#!/bin/sh` + `echo a`) and a
    symlink `H/.local/bin/l4-tool-b` to `H/.local/share/l4-test/versions/1/tool-b` (same kind of script); PATH starts
    with `H/.local/bin`; `l4-tool-a && l4-tool-b` exits 0 in B's gate and agent sandboxes.
  - `test_a_units_key_files_are_hidden_from_another_unit` (SCN-PRV-100): unit A (`opencode`) writes
    `write_key_file(wa.agent_tmp / "opencode-config", "sk-PROFILE-A-PROVIDER-KEY")` and
    `write_credential_file(wa.agent_tmp, "sk-PROFILE-A-LOADER-VALUE")`; B's gate and agent read neither, both under the
    default cache (`H/.cache/l4`) and under a `L4_CACHE` outside `H` (parametrized), and both files still hold their
    values on the host.
- [ ] 2.2 Argv and config tests (no bwrap needed). `tests/unit/sandbox/test_bwrap_home.py`:
  - `test_the_home_tmpfs_comes_before_every_bind` (SCN-SEC-72): gate and agent spec with worktree, tmp dir, a cache and
    the git dir all under the home: `["--tmpfs", home]` follows `base_flags`, and the index of each of their binds is
    greater.
  - `test_a_home_of_root_is_refused` (SCN-SEC-73): `home=Path("/")`, a relative home and a missing directory each raise
    `SandboxUnavailable` (exit code `DOCTOR_FAILED`) whose message names `HOME`.
  - `test_a_runner_cache_outside_the_home_is_covered` (SCN-SEC-74): `--tmpfs <cache_root>` right after the home's tmpfs,
    then the binds; a cache root inside the home adds no second tmpfs.
  - `test_user_local_tools_are_bound_read_only` (SCN-SEC-76): a fake home tree with the paths of the scenario (plus
    `~/.local/share/uv/credentials/` that must NOT be bound), `l4.sandbox.home.tool_paths(...)` returns the expected
    set, deduplicated, and the argv has one `--ro-bind p p` per path, before the credential masks.
  - `test_a_tool_bind_never_re_exposes_a_login` (SCN-SEC-77).
  - `test_setup_paths_reach_only_a_setup_gate` (SCN-SEC-79): `gate_sandbox_spec(..., builds_env=True)` binds
    `~/.npmrc` read-only; `builds_env=False` and an agent spec do not.
  - `test_the_hello_key_directory_is_hidden` (SCN-PRV-103): `ProbeCtx(environ, cache_root, fake_run)` with
    `l4.agents.opencode_provider.reachable` patched to `(True, "")`; `fake_run` reads the `{file:<path>}` of the
    provider key from `OPENCODE_CONFIG_CONTENT` and records the directory's mode and location; the directory is 0700
    and under `cache_root`, and a gate argv with that `cache_root` has `--tmpfs <cache_root>` and no bind of a path
    at or above the directory.
  `tests/unit/config/test_sandbox_paths.py::test_a_tool_path_inside_a_login_is_refused` (SCN-SEC-80): `tool_paths` and
  `setup_paths` entries `/`, `~`, `~/.codex/bin`, `~/.codex`, `~/.local/share` (holds opencode's login) and `relative`
  each fail `load_config` with exit 2 naming the key, and the message never holds the path; `~/.local/opt` loads; an
  entry that contains `$L4_CACHE` raises `L4Exit(USAGE_ERROR)` from `l4.sandbox.home.tool_paths`.
- [ ] 2.3 Code, sandbox layer: `src/l4/sandbox/base.py`: `SandboxSpec` gains keyword-only fields with no default
  `cache_root: Path` and `tool_paths: tuple[Path, ...]`, and `setup_paths: tuple[Path, ...] = ()`;
  `gate_sandbox_spec(..., cache_root, tool_paths, setup_paths=(), builds_env: bool)` (keyword, required) keeps
  `setup_paths` only when `builds_env`. New `src/l4/sandbox/home.py`: `tool_paths(host_env, *, home, cache_root, kind,
  configured, forbid)` (design D4, items 1-9, in that order, deduplicated), `setup_paths(host_env, *, home, cache_root,
  configured)`, and `hidden_roots(spec)`. `src/l4/sandbox/bwrap.py`: `build_argv` in design D3's order with the home
  refusal of D1; update the module docstring (line 17: "empty home" is built; name L4-SEC-030..032). Update
  `tests/unit/sandbox/conftest.py` (`make_spec`) and the argv tests whose expected order changes
  (`test_bwrap_argv.py::test_gate_argv_shape`, `::test_main_repo_git_dir_is_read_only_and_after_the_writable_binds`,
  `::test_the_runner_tmp_dir_is_covered_by_a_tmpfs_in_both_kinds_before_any_bind`). Verify: 2.2 files, `tests/unit/sandbox/`.
- [ ] 2.4 Code, configuration and callers: `src/l4/config/schema.py` `SandboxCfg.tool_paths: list[str] = []` and
  `setup_paths: list[str] = []` with the validator of design D5 (`ValueFree`). Every `SandboxSpec` constructor passes
  `cache_root` and `tool_paths` from `l4.sandbox.home`: `implementer/workbench.py` (`agent_spec` with `kind="agent"`,
  `gate_spec`, which gains `builds_env: bool = False` and passes `sandbox.setup_paths`), `yolo/readiness.py:515`,
  `sim/dryrun.py:109`, `gates/dryrun.py:242` (`builds_env = gate == "setup"`), `yolo/postcheck.py:179` (its setup
  items). `Workbench.run_gate` and `run_gate_spec` gain `builds_env: bool = False`; it is `True` in `tdd.run_setup`,
  `verifier/gates.run_build_gates` (name `setup`), `uvseed._fill`, and the `setup-base` gates of
  `verifier/playwright.base_checkout` (via `gates/e2e.py`). Update every test that builds a `SandboxSpec` directly
  (`grep -rln "SandboxSpec(" tests`: `tests/unit/gates/test_runner.py`, `tests/unit/agents/test_judge_cwd.py`,
  `tests/unit/agents/test_login_lock.py`, `tests/unit/sandbox/test_select.py`, the two parity tests). Verify: the 2.2
  config test, `tests/unit/config/`, `tests/unit/yolo/`, `tests/unit/sim/`, `tests/unit/gates/`, `tests/unit/agents/`.
- [ ] 2.5 Parity: `scripts/runner/sandbox-probe.sh` and `scripts/runner/ci-probe-m15.sh` (`m0-profile` blocks) build
  the new argv: `--tmpfs "$HOME"` (exit 3 with a message when `HOME` is `/` or not a directory), new arguments
  `root:DIR` (the runner cache: `--tmpfs` when outside `$HOME`) and `tool:DIR` (one `--ro-bind` each) and, for the m15
  gate kind, `ro:DIR` and `empty:DIR` (task 4.4), in design D3's order. Their own call sites pass `root:` from
  `${L4_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/l4}` and `tool:` for each PATH entry under `$HOME` plus `$L4_HOME`
  (a documented subset of D4). Tests: extend the `world` fixtures of `tests/unit/sandbox/test_probe_parity.py` and
  `tests/unit/runner/test_probe_m15_parity.py` with a `cache_root` and two tool paths (one with a space) so every
  existing parity test covers the new flags, and add `test_the_probe_covers_the_home_and_the_cache_like_the_sandbox`
  to the first.

## 3. Key and credential files (sandbox-security-4; L4-PRV-040, L4-PRV-041)

- [ ] 3.1 Tests: `tests/unit/agents/test_opencode_provider.py::test_private_dirs_are_0700_and_no_key_outlives_the_step`
  (SCN-PRV-101): with the file's `request` helper and a fake runner that, during the run, records the modes of
  `req.result_path.parent`, of `opencode-config` and of `provider.key`: 0700, 0700, 0600; after a run that returns and
  after one that raises, neither `provider.key` nor `credential` exists (use an `auth: api_key` opencode-go profile with
  `OPENCODE_API_KEY` set for the loader file). `tests/unit/implementer/test_credential_leftovers.py::
  test_a_key_left_by_a_killed_run_is_removed` (SCN-PRV-102): with `make_bench`, write
  `<unit_cache>/agent-tmp/opencode-config/provider.key` and `<unit_cache>/agent-tmp/credential`, build a second
  workbench for the unit (`make_workbench` with the bench's arguments): both files are gone.
- [ ] 3.2 Code: `src/l4/implementer/workbench.py`: `__post_init__` unlinks `agent-tmp/opencode-config/provider.key`
  and `agent-tmp/credential` (names from `l4.agents.opencode_provider.KEY_FILE`, `l4.agents.opencode.CONFIG_DIR`,
  `l4.agents.credentials.CREDENTIAL_FILE`) before it creates the directories; `reset_agent_tmp` and the creation of
  `agent-tmp`/`gate-tmp` use mode 0700 (`mkdir(mode=0o700)` then `chmod(0o700)`: the umask can only remove bits).
  `src/l4/agents/opencode.py:213` creates `opencode-config` with 0700; `src/l4/agents/credentials.py:105` likewise for
  a directory it creates. Verify: 3.1 files, `tests/unit/agents/test_opencode*.py`, `tests/unit/sandbox/test_credential_env.py`,
  `tests/unit/implementer/`.

## 4. The project environment (implementer-2; L4-SEC-035..037)

- [ ] 4.1 Tests, ported from `verify-implementer/repo/tests/unit/implementer/test_verify_impl2_venv.py` and
  `verify-implementer/repro_impl2_uv_sync.sh`:
  - `tests/unit/implementer/test_env_plant.py::test_a_pth_planted_by_green_does_not_make_green_pass` (SCN-SEC-88):
    copy the reproduction (the `MKREALVENV` setup script that builds `.venv` with `python -m venv --without-pip` and
    writes `_host.pth` pointing at the host's site-packages, the `PTH` line setting `PYTEST_PLUGINS=l4plant`, the
    `PLUGIN` hookwrapper that turns failures into passes, the green `Step` writing `zz_l4.pth` and `l4plant.py` into
    `.venv/lib/pythonX.Y/site-packages`, `make_bench([red_step(), green], setup=[...])`, `run_red`, `run_green`).
    Assert the opposite of the reproduction: green's status is not `ok`, `pricing.py` is still the stub and no green
    commit was made, `zz_l4.pth` and `l4plant.py` are gone after green, one `guard.violation` has `rule ==
    "environment"` and a path ending in `zz_l4.pth`, and an `env.rebuilt` event names `.venv`.
  - `tests/unit/implementer/test_env_plant_uv.py::test_plants_that_survive_uv_sync_are_removed` (SCN-SEC-89): the shell
    reproduction in Python (`subprocess`, skip without uv): a `pyproject.toml` with no dependencies, `uv lock`, `uv sync
    --frozen`, `envguard.take_manifest`, write `zz_planted.pth` and `sitecustomize.py` (the reproduction's contents),
    `uv sync --frozen` again and assert both survive (the reason for L4-SEC-036), then `envguard.planted(...)` lists both,
    `envguard.remove_env_dir` + `uv sync --frozen` builds `.venv` without them, and `.venv/bin/python -c` shows neither
    variable set.
- [ ] 4.2 Tests: `tests/unit/implementer/test_envguard.py`, with `make_bench` (NoSandbox) and a fake venv built by the
  setup script of 4.1:
  - `test_a_declared_dependency_is_rebuilt_without_a_violation` (SCN-SEC-90): an agent step that changes
    `pyproject.toml` and `uv.lock` and adds `site-packages/newdep/__init__.py` plus `newdep-1.0.dist-info/RECORD`
    listing it with its real sha256: `env.rebuilt{declared: true}`, `.venv` removed, no `guard.violation`.
  - `test_a_gate_plant_under_mode_none_is_removed` (SCN-SEC-91): a test gate command that writes `sitecustomize.py`
    into site-packages; after `wb.run_gate("test", ...)`: `.venv` removed, `guard.violation{phase: "gate", rule:
    "environment"}`, `wb.setup_at is None`.
  - `test_a_changed_node_package_is_removed` (SCN-SEC-92): a manifest taken over a `node_modules/vitest/dist/index.js`,
    an agent step that edits it: `node_modules` removed, the violation names the file.
  - `test_an_environment_a_gate_created_is_removed` (SCN-SEC-93): `setup=[]` and a test gate that creates `.venv`:
    removed after the gate, `env.rebuilt{reason: "created"}`.
  - `test_the_verifiers_first_setup_rebuilds` (SCN-SEC-94): a second workbench on the same worktree (as
    `verifier/ladder.py:1289` builds one) after a file was added to `.venv`: its first setup gate removes `.venv` first
    (`env.rebuilt{reason: "unverified"}`), and the file is not in the rebuilt `.venv`.
  - `test_the_first_setup_in_a_fresh_worktree_removes_nothing` (SCN-SEC-95): no `env.rebuilt`, a manifest after setup.
  - `test_a_tracked_node_modules_is_never_removed`: a committed `vendor/node_modules/x.js` changed by a step is left to
    the production guards, and `env_dirs` does not list it.
- [ ] 4.3 Tests: `tests/unit/sandbox/test_env_dirs.py::test_tool_caches_start_empty_in_every_gate` (SCN-SEC-87): the
  gate argv of a worktree with `.venv` and `node_modules/.vite` has `--ro-bind` of both after the git dir bind, then
  `--tmpfs <node_modules/.vite>`, then the guidance masks; a setup gate's argv has neither; `envdirs.reset_tool_caches`
  turns a `.vite/deps/x.js` into an empty `.vite` and replaces a symlinked `.cache` with an empty directory. Live, in
  `tests/unit/sandbox/test_bwrap_live_env.py` (`@requires_bwrap`): `test_a_test_gate_cannot_write_the_environment`
  (SCN-SEC-85) and `test_uv_run_works_on_the_read_only_environment` (SCN-SEC-86, also skipped without uv; if it fails,
  apply the `.venv/.lock` fallback of design D6 and say so in the commit).
- [ ] 4.4 Code: new `src/l4/sandbox/envdirs.py` (design D6: `ENV_DIR_NAMES`, `TOOL_CACHE_DIRS`, `env_dirs`,
  `read_only_mounts`, `reset_tool_caches`). `src/l4/sandbox/base.py`: `SandboxSpec.read_only` and `empty_dirs`
  (tuples, default `()`); `gate_sandbox_spec` fills them from `read_only_mounts(worktree, tracked)` when `builds_env` is
  false (the caller passes `tracked`, from `git ls-files -z` of the env directory names). `src/l4/sandbox/bwrap.py`:
  emit them after the git dir bind and before the guidance masks. Verify: 4.3 files, `tests/unit/sandbox/`.
- [ ] 4.5 Code: new `src/l4/implementer/envguard.py` (design D7: `Entry`, `EnvManifest`, `take_manifest`,
  `diff_manifest`, `planted`, `remove_env_dir`, `DECLARING_FILES`). Verify: the uv test of 4.1 and the pure parts of 4.2.
- [ ] 4.6 Code, wiring: `src/l4/implementer/workbench.py`: `env_manifests`, `check_env(tree, *, phase, changed=())`,
  and in `run_gate_spec` the `builds_env` behaviour of design D7 (remove an unverified environment before a setup gate,
  manifest after a passing one; `reset_tool_caches` before, `check_env` after, any other gate).
  `src/l4/implementer/tdd.py`: `agent_step`'s `finally` calls `wb.check_env(wb.worktree, phase=role,
  changed=wb.changed_files())` after `restore_ledger`; the comment at line 1205 says what is true now.
  `src/l4/implementer/guardnotes.py`: `_ADVICE["environment"]` (design D7 text). Verify: all of 4.1 and 4.2,
  `tests/unit/implementer/`, `tests/unit/verifier/`.

## 5. Doctor `SANDBOX-003` (L4-SEC-038)

- [ ] 5.1 Tests: `tests/unit/doctor/test_checks_sandbox_003.py`: `test_a_readable_canary_fails` (SCN-SEC-96, with a
  fake runner as `tests/unit/doctor/test_checks_sandbox.py` uses, printing `L4-READ:<home canary>` for the agent kind:
  fails, names the path and `agent`, the result text holds no canary marker, no canary file is left), and
  `test_skipped_without_a_bwrap_sandbox` (SCN-SEC-98: `sandbox.mode: none` with `allow_none`, and no bwrap on PATH, each
  skip with a reason naming the cause). Live: `test_the_real_argv_passes` (SCN-SEC-97, `@requires_bwrap`, with `HOME`
  and `L4_CACHE` under `/var/tmp`).
- [ ] 5.2 Code: `src/l4/doctor/checks_sandbox.py`: `_sandbox_003` and `SANDBOX_003 = register(Check("SANDBOX-003",
  "The sandboxes hide the home and the runner cache", "error", _sandbox_003))` as design D10 says. Verify: 5.1 files,
  `tests/unit/doctor/`.

## 6. Docs

- [ ] 6.1 `docs/SPEC.md`:
  - §18: append `**L4-SEC-030**` ... `**L4-SEC-038**` after L4-SEC-008 (the requirement texts of this change's
    `specs/security/spec.md`, with the details of design D1-D7 and D10 that a reader of the SPEC needs: the argv order,
    the tool path list, the manifest rule, the classification). In L4-SEC-005 replace "an **empty home**" with "an **empty
    home** (L4-SEC-030: a tmpfs over the real home, the tool paths of L4-SEC-032 read-only)", "the per-unit cache mounts
    of `sandbox.caches`" with "the per-unit cache mounts of `sandbox.caches` (keyed by the repository key, L4-SEC-034)",
    and "`HOME` inside a sandbox is a private directory holding only the mounts above" with "`HOME` inside a sandbox is a
    tmpfs over the real home holding only the mounts above, and the runner cache is a tmpfs too (L4-SEC-030,
    L4-SEC-031)".
  - §8.3: append `**L4-PRV-040**` and `**L4-PRV-041**` after L4-PRV-028; in 8.3.1 step 1 of the credential loader add
    "(0700, visible only in the step's own agent sandbox, L4-PRV-040)"; in the OpenCode provider paragraph after "removes
    it when the run ends, whatever the outcome" add "; a file left by a killed run is removed when the unit's next
    workbench is built (L4-PRV-041)".
  - L4-CFG-005: "which is why both paths are keyed" becomes "which is why these paths, and every per-unit directory
    (L4-SEC-034), are keyed".
  - §3.2 config block under `sandbox:`: `tool_paths: []` and `setup_paths: []` with one-line comments, and on `caches:`
    "`{unit}` = `<repository key>/<framework>/<name>`".
  - §17 doctor table: a `SANDBOX-003` row after `SANDBOX-002` (severity error; what it plants and runs; skipped when
    bwrap is absent or the mode is not `auto`/`bwrap`).
  - The ledger event list: `env.rebuilt` (`{tree, dirs, phase, added, changed, removed, reason, declared,
    planted_more}`), and rule `environment` on `guard.violation`.
  - Part II: a new section `### 23.24 Sandbox isolation (SEC, PRV)` with SCN-SEC-70..98 and SCN-PRV-100..103 in SPEC
    form (`#### SCN-SEC-70 (−) <title> · L4-SEC-030`, `- **Given** / **When** / **Then**`), the texts of this change's
    scenarios.
  - §21 change table: a row after the last one present, `sandbox-isolation` (an empty home and a hidden runner cache in
    both sandbox kinds, read-only tools, keyed per-unit directories, a project environment rebuilt when a step or a gate
    changed it, key files visible only to their step, doctor `SANDBOX-003`; L4-SEC-030..038, L4-PRV-040..041;
    `openspec/changes/sandbox-isolation/`) with its acceptance (SANDBOX-003 passes on `l4-runner` and on a GitHub-hosted
    runner; the dummy repository's gates stay green).
  Run `python scripts/check_spec.py docs/SPEC.md`: no uncovered requirement, no undefined reference.
- [ ] 6.2 `CHANGELOG.md` under `## 0.4.16 (unreleased)` (create the heading above the newest release when it is absent):
  `### Fixed` for the four findings in consumer words (what an agent's test could read or fake before, and that it no
  longer can), `### Added` for `sandbox.tool_paths`, `sandbox.setup_paths` and doctor `SANDBOX-003`, `### Changed` for
  the keyed cache layout (caches start empty once; the old `units/<fw>/<name>` directories can be deleted by hand) and
  the rebuilt environment after a step that changed it. `docs/runbook.md`: in "Known limits" and the sandbox lines,
  what to do when a tool is missing inside the sandbox (`sandbox.tool_paths`), a private registry in setup
  (`sandbox.setup_paths`), what `env.rebuilt` and a `guard.violation` with rule `environment` mean, why a project
  without `gates.setup` rebuilds its environment in every gate, and the legacy unpublished-file warning.
  `docs/runner/README.md:259-263`: the sandboxes now cover the home and the runner cache (HB-16 built); SANDBOX-003 is
  the live check; SANDBOX-001 stays unbuilt.

## 7. Live check (orchestrator, after the groups above are merged)

- [ ] 7.1 On `l4-runner` (bwrap 0.6.1, gitlab-runner shell): `l4 doctor` passes `SANDBOX-002` and `SANDBOX-003`; a run
  of the dummy repository's unit passes its gates with an agent of each configured adapter (claude-code, codex,
  opencode); `scripts/runner/sandbox-probe.sh` with `SANDBOX=m0` passes. Record the log in `docs/live/`.
- [ ] 7.2 On a GitHub-hosted `ubuntu-24.04` runner (the evidence workflow): the same doctor rows pass and a unit with a
  `uv` and a `pnpm` project passes its gates. Any tool that is missing inside the sandbox is fixed in `l4.sandbox.home`
  (a default) or documented as a `sandbox.tool_paths` entry before the release.
