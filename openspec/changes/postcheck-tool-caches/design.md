# Design: postcheck-tool-caches

## Decisions

**D1. The reset goes before the spec, in each runner's loop.** `gate_sandbox_spec` calls `read_only_mounts`, which
returns a tmpfs target only for a tool cache that is already a real directory. A reset placed after the spec is built
(next to `run_gate`) would leave bwrap without the tmpfs lines and the gate would fail as before. So each runner
calls `reset_tool_caches(tree, tracked)` at the top of every iteration whose gate is not `gates.setup`, then builds the
spec. This is the order of `Workbench.run_gate_spec`.

**D2. The builder stays pure.** Putting the reset inside `gate_sandbox_spec` would cover every caller at once, but it
would make a spec builder write to the tree, and the doctor's probe builds one too. The two runners are the only other
callers that run project commands, so they get the call, as the workbench has it.

**D3. One tracked-paths function.** The workbench already knows that a `node_modules` git tracks a file in is source,
not an environment (`_tracked_env`). The function moves to `l4.sandbox.envdirs` as `tracked_env_paths(git) ->
frozenset[str]` with the same `git ls-files -z` call; the workbench method returns it. The post-merge check and the
dry run call it with a `Git` of their detached worktree and pass the result to `gate_sandbox_spec(tracked=…)` and to the
reset.

**D4. The setup gate is unchanged.** A `gates.setup` command builds the environment with the caches writable, as now.
The reset before the next gate empties whatever the install left in a cache folder.

## Failure cases

- A symlink or a regular file at a tool cache path: `reset_tool_caches` already unlinks it without following it and
  makes an empty folder.
- No `node_modules` at all (a Python or Go project): `env_dirs` finds none, the reset does nothing.
- A tracked `node_modules`: left out of the reset and of the read-only binds, as in the workbench.
