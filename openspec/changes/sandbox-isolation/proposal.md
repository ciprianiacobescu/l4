## Why

An independent review of 0.4.13 confirmed four sandbox defects with reproductions; all four are still present in 0.4.14
(design section 1 gives the lines):

- **The sandboxes show the real home** (sandbox-security-2, major). Both kinds start from `--ro-bind / /` and hide only
  the adapters' login paths, so agent-written tests read `~/.git-credentials`, `~/.netrc`, `~/.ssh/id_*`,
  `~/.config/gh/hosts.yml` and `~/.docker/config.json` (proved under live bwrap 0.8.0). L4-SEC-005 already says the
  gate sandbox has "an empty home"; `bwrap.py:17` and `docs/runner/README.md:259-263` list it as not built (HB-16).
- **A file planted in `.venv` decides later verdicts** (implementer-2, blocker). A green step that writes only a `.pth`
  file into site-packages passes with the production code still a stub: no guard sees `.venv`, `discard_changes` keeps
  it, `uv sync --frozen` keeps it (proved with real uv 0.10.0), and the same run's verifier runs its gates on it. The
  same holds for `node_modules`.
- **Per-unit directories ignore the repository key** (sandbox-security-1, major). Two projects with a unit of the same
  name on one runner share `agent-tmp`, `gate-tmp`, `excludes`, the uv/pip/npm caches and `pending-unpublished`, so one
  project's unpublished run file is pushed into the other project's lock ref.
- **A unit's OpenCode provider key and credential-loader file are readable from every other sandbox** (sandbox-security-4,
  major): they live under `$L4_CACHE/units/...`, which `--ro-bind / /` shows to every sandbox of the runner user, and the
  default `ci.max_parallel_units: 2` makes the window concurrent.

## What Changes

- **Hidden home and runner cache** (L4-SEC-030, L4-SEC-031): both sandbox kinds cover `$HOME` and `$L4_CACHE` with a
  tmpfs before any bind; the step's own directories, the worktree, the git common dir and the caches come back after it.
  `HOME` keeps its path. A `HOME` of `/` makes the sandbox unavailable (exit 3).
- **Tools stay usable** (L4-SEC-032, L4-SEC-033): user-local tools under a hidden root are bound read-only (the PATH
  entries, the install roots of their symlinks, `$L4_HOME`, uv's Python and tool directories, the corepack home, the
  harness's gate plugins, `~/.serena` for agents); new keys `sandbox.tool_paths` (both kinds) and `sandbox.setup_paths`
  (setup gates only, for a registry login) bind more, read-only, and refuse any path that is or holds a login.
- **Keyed per-unit directories** (L4-SEC-034): `$L4_CACHE/units/<key>/<fw>/<name>`, `{unit}` in `sandbox.caches` =
  `<key>/<fw>/<name>`, `pending-unpublished/<key>/<fw>/<name>`; a run file of the earlier layout is adopted only when its
  commits are in this repository, otherwise kept and named in a warning.
- **The project environment cannot carry a plant into a verdict** (L4-SEC-035..037): gates other than `gates.setup` see
  `.venv` and `node_modules` read-only (their `.cache`/`.vite` start empty); after every successful setup the harness
  records a manifest of the environment, and after every agent step and every other gate a changed, new or unverified
  environment is removed and rebuilt by the next setup, with `env.rebuilt` and a `guard.violation` (rule `environment`)
  per planted path; a workbench's first setup in a tree rebuilds it, so the verifier never runs on the implementer's.
- **Credential files are visible only to their own step** (L4-PRV-040, L4-PRV-041): 0700 step directories, 0600 files,
  removed at the end of the step and, after a killed run, before the unit's next agent or gate.
- **The login and unit lock files are unreadable in the sandboxes** (sandbox-security-6, owner decision Q3): a
  consequence of the two tmpfs, claimed fixed only because SCN-SEC-99 proves it with the harness's own lock paths.
- **Doctor `SANDBOX-003`** (L4-SEC-038) plants canaries in the home, in another unit's step directory and in the lock
  directory and fails closed (exit 3) when either sandbox kind reads one.
- `scripts/runner/sandbox-probe.sh` follows the new argv (parity test); the runbook, the runner README and the SPEC are
  amended.

## Impact

- Code: `src/l4/sandbox/{base.py,bwrap.py,caches.py}`, new `src/l4/sandbox/home.py` and `src/l4/sandbox/envdirs.py`,
  new `src/l4/implementer/envguard.py`, `src/l4/implementer/{workbench.py,tdd.py,uvseed.py,guardnotes.py}`,
  `src/l4/vcs/names.py`, `src/l4/state/{pending.py,restart.py}`, `src/l4/orchestrator.py`,
  `src/l4/verifier/{gates.py,basemerge.py,playwright.py,fixloop.py}`, `src/l4/gates/{dryrun.py,e2e.py}`,
  `src/l4/yolo/{postcheck.py,readiness.py}`, `src/l4/sim/dryrun.py`, `src/l4/agents/{opencode.py,credentials.py}`,
  `src/l4/config/{schema.py,defaults.py}`, `src/l4/doctor/checks_sandbox.py`, `scripts/runner/sandbox-probe.sh`.
- Spec: L4-SEC-030..038 and L4-PRV-040..041 added; L4-SEC-005 parts b, c, d modified; L4-CFG-005 and the SPEC text of
  L4-SEC-005 amended in `docs/SPEC.md`; SCN-SEC-70..99, SCN-PRV-100..104; doctor row `SANDBOX-003`; config keys
  `sandbox.tool_paths`, `sandbox.setup_paths`; event `env.rebuilt`.
- Behaviour per environment (design section 4): on Linux with bwrap (GitHub-hosted and self-hosted) all of it; on a mac with
  `sandbox.mode: none` (accepted risk) only the keyed directories, the environment rebuild and the file modes.
- Migration: per-unit caches start empty under the keyed layout (a new uv cache gets the project's seed copy); the old
  `units/<fw>/<name>` directories are left alone. Python and Node environments are rebuilt once per verification.
- Docs: `docs/SPEC.md`, `docs/runbook.md`, `docs/runner/README.md`, `CHANGELOG.md` (`## 0.4.16 (unreleased)`).
