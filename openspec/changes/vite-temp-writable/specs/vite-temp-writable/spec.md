## Purpose

A test gate that does not build the environment can load a Vite configuration: Vite's config temp folder inside
`node_modules` is a tool cache that starts empty and writable in every gate.

## ADDED Requirements

### Requirement: L4-SEC-035 tool caches include Vite's config temp folder
The gate sandbox of any command other than `gates.setup` SHALL treat `node_modules/.vite-temp` like
`node_modules/.cache` and `node_modules/.vite`: empty at the start of every such gate (the harness empties or makes it
before each gate in every sandbox mode, and under bwrap a tmpfs covers it after the read-only bind of `node_modules`),
and left out of the environment manifest of L4-SEC-036.

#### Scenario: a test gate loads a Vite configuration
- **WHEN** a worktree's `node_modules` holds no `.vite-temp` and a test gate under bwrap runs a command that creates
  `node_modules/.vite-temp/x.mjs`
- **THEN** the command succeeds, the gate's argv has `--tmpfs <worktree>/node_modules/.vite-temp` after the read-only
  bind of `node_modules`, and after the gate the real `node_modules/.vite-temp` is an empty folder

#### Scenario: an earlier gate's file in .vite-temp does not reach the next gate
- **WHEN** `node_modules/.vite-temp` holds a file before a test gate, under bwrap or under `sandbox.mode: none`
- **THEN** the folder is empty when the gate starts, and the environment check after the gate reports no change

#### Scenario: a planted link at .vite-temp is replaced
- **WHEN** `node_modules/.vite-temp` is a symlink before a test gate
- **THEN** the harness unlinks it without following it and makes an empty folder in its place
