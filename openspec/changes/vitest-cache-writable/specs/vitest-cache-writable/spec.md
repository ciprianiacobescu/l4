## Purpose

A test gate that does not build the environment can run a Vitest 5 suite with its default module cache: Vitest's
module cache folder inside `node_modules` is a tool cache that starts empty and writable in every gate.

## ADDED Requirements

### Requirement: L4-SEC-035 tool caches include Vitest's module cache
The gate sandbox of any command other than `gates.setup` SHALL treat `node_modules/.vitest-cache` like
`node_modules/.cache`, `node_modules/.vite` and `node_modules/.vite-temp`. It SHALL be empty at the start of every
such gate: the harness empties or makes it before each gate in every sandbox mode, and under bwrap a tmpfs covers it
after the read-only bind of `node_modules`. The environment manifest of L4-SEC-036 SHALL leave it out.

#### Scenario: a test gate writes Vitest's module cache
- **WHEN** a worktree's `node_modules` holds no `.vitest-cache` and a test gate under bwrap runs a command that
  creates `node_modules/.vitest-cache/<key>`
- **THEN** the command succeeds, the gate's argv has `--tmpfs <worktree>/node_modules/.vitest-cache` after the
  read-only bind of `node_modules`, and after the gate the real `node_modules/.vitest-cache` is an empty folder

#### Scenario: a cached module from an agent step does not reach the next gate
- **WHEN** an agent step writes a file into `node_modules/.vitest-cache` and a test gate follows, under bwrap or
  under `sandbox.mode: none`
- **THEN** the environment check after the step reports no change and rebuilds nothing, and the folder is empty when
  the gate starts

#### Scenario: a planted link at .vitest-cache is replaced
- **WHEN** `node_modules/.vitest-cache` is a symlink before a test gate
- **THEN** the harness unlinks it without following it and makes an empty folder in its place
