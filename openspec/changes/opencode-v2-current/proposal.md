## Why

The OpenCode 2 adapter (`opencode-v2`, row 68) shipped in 0.4.28 as experimental, pinned at `@opencode/cli` 2.0.32 and
built from recordings made with no key. Its live validation (groups B8 and B9 of that change) was deferred. Since then
`@opencode/cli` moved on to 2.2.6 (2026-11-06, `latest`), and a live check has now been run on that version: L4's own
`OpenCodeV2Adapter.probe` and `run` drove the real binary with a paid `opencode-go/` key and a free `opencode/` model,
on macOS without a sandbox and in a Linux container through L4's real bubblewrap sandbox with an agent `SandboxSpec`
built the way `Workbench.agent_spec` builds it.

The core paths hold on 2.2.6 with the adapter as it is: the probe ladder, a judge reply (paid and free), an implementer
edit and its result file, the step bound, `options.tools`, the session export and its usage. The same check found three
gaps that the 0.4.28 design did not cover:

1. **OpenCode's own tools reach an implementer** (G1). The implement-mode `permissions` array names the tools L4 wants
   and leaves every other action at OpenCode's default. An implementer was offered `worktree_create`, `worktree_list`,
   `worktree_remove`, `session_move`, `session_rename`, `models`, the MCP resource tools, `execute` (Code Mode, which
   calls those tools from JavaScript) and `experimental_image_generate`, and it created a git worktree with
   `worktree_create`, on 2.0.32 and on 2.2.6. Inside the agent sandbox the read-only git common directory made it fail;
   a run without a sandbox kept the worktree.
2. **The agent's shell can start the OpenCode CLI** (G2). `opencode2` is on the agent's `PATH`. `opencode2 api …` worked
   from the shell and, without `--standalone`, started the shared background service. Outside a sandbox the service
   outlived the run; inside, it died with the sandbox. One such run was also disturbed by it: the stream ended without
   its final `step_finish`.
3. **Every run shares one data home** (G3). `XDG_DATA_HOME` is never redirected, and `~/.local/share/opencode` is bound
   read-write into every opencode step. v2 keeps its sessions, stored shell outputs, worktrees and logs there. From one
   sandboxed step, `opencode2 api GET /api/project` listed the projects of every earlier step on that machine. The same
   root makes v2 migrate the runner user's `opencode.db` (amendment E6 of `opencode-v2`).

This change pins the version that was checked, closes the three gaps for the profiles where that is safe, and calls the
adapter supported, with the facts no run has recorded kept on their named fallbacks.

## What Changes

- **Pin `@opencode/cli` 2.2.6** (L4-OCV-019, amends L4-OCV-002). `OPENCODE2_VERSION`, the install command,
  `prereqs.sh` PRQ-20, the runner README and every test or document that names 2.0.32 as the pin. The 2.0.32
  recordings stay as history; the live recordings of 2.2.6 go to `tests/fixtures/recorded/opencode/2.2.6/live-*`.
- **Implement-mode permissions are an allow-list** (L4-OCV-015). The array starts with `*:* <refuse>` (`deny` for a paid
  model, `ask` for an `opencode/` model, as the judge already does), then today's rules. Every OpenCode tool L4 does not
  name, and every tool a later OpenCode adds, starts refused. `worktree_remove` and `skill` stay offered (OpenCode gates
  the first with `edit` and keeps the second in every mode). That is a stated residual: the agent sandbox's read-only
  git common directory makes the first fail, and no skill source is visible to the second. The `options.tools` path
  (already `*:* deny` first) and judge mode do not change.
- **The shell may not start the OpenCode CLI** (L4-OCV-016). `shell` denies for `opencode*`, `opencode2*` and
  `*bin/opencode*` next to the git denies, wherever `shell` is allowed. They apply to v2 only: v1 has no
  auto-started daemon, and its rules stay byte-identical (design D3).
- **A private data home for a v2 profile that needs no stored login** (L4-OCV-017). This covers `auth: api_key` with
  `OPENCODE_API_KEY` and any `opencode/` model. The run and its `session export` share `<step dir>/opencode2-data`, and
  the hello uses a `data` directory in its scratch. Such a profile's auth step never starts `auth list`. `uv`'s Python
  and tool directories are passed explicitly, so the agent's shell still finds what the sandbox binds. A profile with a
  stored login keeps today's data home, because v2 keeps that login in `opencode.db` there.
- **Such a profile's sandbox does not bind the real OpenCode data and config homes** (L4-OCV-018). The process uses its
  private ones, so `~/.local/share/opencode`, `~/.config/opencode` and every other own login path outside the cache home
  are hidden instead of bound read-write, and `~/.cache/opencode` stays bound (shared read-write, v1 and v2 alike; a
  per-unit cache is a follow-up). v1 profiles and stored-login v2 profiles bind exactly as before.
- **Supported, not experimental** (L4-OCV-019, amends L4-OCV-001 and L4-OCV-013). `experimental = True` goes, so
  `agent.experimental` is no longer recorded. The v1 gate reason ends `or set options.cli_major: 2 to run OpenCode 2`
  (L4-OCG-002). The SPEC row, the CHANGELOG, the runbook section and the plan stop calling the adapter experimental.
- **[U] rows recorded on 2.2.6 become [V]**, each with its live fixture: U2, U5, U7 (the bounded run and `failed`), U9
  (in part) and U11. Their fallbacks matched the recordings, so no parser changes. U1, U3, U4, U6 and U10 stay open on
  their fallbacks and are listed as known fallbacks in the runbook. U8 now applies only to a stored-login profile.
- **Fixtures**: eight scrubbed live runs (stream plus export) under `tests/fixtures/recorded/opencode/2.2.6/`, with a
  README line each. The parser tests point at them.
- **Not changed**: the delegate on v2 stays out of scope (L4-OCV-014). There is still no read-only mode for v2.

## Impact

- Capability `opencode-v2-current`. Code:
  - `src/l4/agents/opencode_v2.py` (the allow-list, the CLI denies, the private data home, no `experimental`)
  - `src/l4/agents/credentials.py` (`no_stored_login`)
  - `src/l4/sandbox/base.py`, `src/l4/sandbox/bwrap.py`, `src/l4/sandbox/home.py`
  - `src/l4/implementer/workbench.py`, `src/l4/yolo/readiness.py` (the spec flag)
  - `src/l4/provision/catalog.py` (the pin and the v1 gate text)
  - `scripts/runner/prereqs.sh`
  - `src/l4/recorded_versions.json` (regenerated)
- **Every consumer's agent-CLI cache is rebuilt once on upgrade.** `catalog_pins` holds `agent:opencode2`, so the
  pin move changes `catalog_hash` (L4-ACT-002) whether or not a v2 profile exists, as the 0.4.28 pin did.
- **v1 is unchanged**: the same argv, `OPENCODE_CONFIG_CONTENT` and sandbox binds (SCN-OCV-01, SCN-OCV-41).
- A v2 profile that needs no stored login no longer touches the runner user's `opencode.db`. Its runs, exports and
  hellos use private data homes, so the "a runner user that no v1 profile shares" rule (U8, E6) applies only to v2
  profiles with a stored login.
- What the live check did not cover, and is not claimed: a whole L4 unit (orchestrator, ladder, verifier) on v2 in CI
  (the check drove the adapter's `probe` and `run` directly), a 402 or 429, the custom provider key file, an OAuth
  refresh failure, a guidance canary and SIGINT (design D7).
- Depends on `opencode-v2` (0.4.28). No new runtime dependency.
