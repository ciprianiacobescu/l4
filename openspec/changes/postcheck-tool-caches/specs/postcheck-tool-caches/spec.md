## Purpose

Every runner of project gates gives the tool caches of L4-SEC-035 the same empty, writable start: the post-merge check
and the gate dry run as well as the implementer's and the verifier's gates.

## ADDED Requirements

### Requirement: The post-merge check and the gate dry run empty the tool caches before each gate
Before every gate that is not a `gates.setup` command, the post-merge check of L4-YOLO-009 and the gate dry run SHALL
empty or make each of `node_modules/.cache`, `.vite`, `.vite-temp` and `.vitest-cache` in every `node_modules` of
their worktree that git tracks no file in, before they build that gate's sandbox spec, so that under bwrap each one
gets its tmpfs after the read-only bind of `node_modules`. They SHALL pass the worktree's tracked environment paths to
the sandbox spec and to the reset, as the workbench does.

#### Scenario: a test gate after a fresh install finds the caches
- **WHEN** a profile's setup gate creates `node_modules/pkg/index.js`, a file `node_modules/.vite/stale` and a symlink
  at `node_modules/.vitest-cache`, and the next gate checks the four tool caches
- **THEN** each of the four is a real, empty directory when that gate starts, the symlink's target is untouched, and
  the profile passes

#### Scenario: the gate dry run does the same
- **WHEN** the dry run's setup gate creates the same files and its next gate checks the four tool caches
- **THEN** each of the four is a real, empty directory when that gate starts

#### Scenario: a tracked node_modules is source
- **WHEN** the revision tracks `vendor/node_modules/lib.js` and has a file `vendor/node_modules/.cache/keep`
- **THEN** after the check `vendor/node_modules/.cache/keep` is still there, in the post-merge check and in the dry run
