# Design: vitest-cache-writable

## Decisions

**D1. One more tool cache, not a writable `node_modules`.** L4-SEC-035 keeps an environment that agent-written code
cannot change. The tool caches are the named exceptions, and each one starts empty in every gate. `.vitest-cache` is
where Vitest 5 keeps transformed modules (`<workspace root>/node_modules/.vitest-cache/<sha1>`, plus `_metadata.json`
and `CACHEDIR.TAG`). Adding the name to `TOOL_CACHE_DIRS` reaches every place that already treats `.cache`, `.vite` and
`.vite-temp` this way:
- `reset_tool_caches` empties or makes it before each gate, in every sandbox mode;
- `read_only_mounts` puts it on the tmpfs list under bwrap;
- the manifest walk of `l4.implementer.envguard` leaves it out at the top level of a `node_modules`.

This is the follow-up that `sandbox-isolation` design R4 names: add a directory to `TOOL_CACHE_DIRS` once a live run
shows a tool that needs it.

**D2. Emptied, not kept.** Vitest keys each entry by a sha1 of the module id, its source and the environment's
configuration, and reads the code back without checking it any further. A kept cache would let one gate's (or one
agent step's) planted entry replace a module in the next gate. So the folder is emptied before every gate like
`.vite/deps`, and the gate starts cold. A missing folder is made before the gate: bwrap needs the mount point under the
read-only bind, and a project whose Vitest never ran gets an empty folder it never uses, as it does for the other
three.

**D3. The agent steps follow without a change of their own.** An agent sandbox keeps `node_modules` writable. The
cache files that an agent's own Vitest run writes are now outside the manifest, so the environment check after the
step finds no change and rebuilds nothing. The reset before the next gate removes them.

## Failure cases

- A symlink or a regular file at `node_modules/.vitest-cache`: it is unlinked without being followed and replaced by
  an empty folder, as for `.vite`.
- `sandbox.mode: none`: the reset before each gate is the whole protection, as for the other three.
- `fsModuleCachePath` pointing outside `node_modules`: not a tool cache. The worktree is writable in a test gate, so the
  `mkdir` succeeds there, and the protected-path and environment rules are unchanged.
