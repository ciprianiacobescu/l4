# Design: vite-temp-writable

## Decisions

**D1. One more tool cache, not a writable `node_modules`.** L4-SEC-035 keeps an environment that agent-written code
cannot change; the tool caches are the named exceptions that start empty in every gate. `.vite-temp` is the folder
Vite 5 and later write a bundled config file to (`<nearest node_modules>/.vite-temp/<config>.timestamp-<n>.mjs`) and
remove after loading it; it holds nothing between runs, so emptying it before each gate costs nothing and a tmpfs over
it gives a gate nothing to plant in a later one. Adding the name to `TOOL_CACHE_DIRS` reaches every place that already
treats `.cache` and `.vite` this way: `reset_tool_caches` (empties or makes it before each gate, in every sandbox mode),
`read_only_mounts` (its tmpfs list under bwrap) and the manifest walk of `l4.implementer.envguard` (left out).

**D2. A missing `.vite-temp` is made before the gate.** bwrap needs the mount point to exist under the read-only bind,
and `reset_tool_caches` already makes a missing tool cache; a project whose Vite never ran gets an empty folder it never
uses, as it does for `.vite` today.

## Failure cases

- A symlink or a regular file at `node_modules/.vite-temp`: unlinked and replaced by an empty folder, as for `.vite`.
- `sandbox.mode: none`: the reset before each gate is the whole protection, as for the other two.
