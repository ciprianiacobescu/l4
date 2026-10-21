## Why

A second consumer repository is a polyglot monorepo: Python services, seven Go modules (`go.work`, Go 1.26), and a
TypeScript admin UI (Node 22, pnpm 11). L4 gates only its Python parts. The setup action provisions Python, uv and the
agent CLIs, and nothing else; the configuration has no way to add a toolchain to the L4 job, and `l4 upgrade`
re-renders the workflow, so a step added by hand is lost. The gate sandbox would see a toolchain the job installs: it
mounts the host root read-only and the gates run with the host PATH. So the missing piece is the job, not the sandbox.

## What Changes

- **`ci.toolchains`** (L4-CI-005): `go` (`version` or `version_file`, e.g. `go.work`), `node` (`version` or
  `version_file`), `pnpm` (`version`). The GitHub renderer emits, before the L4 action, the pinned-sha steps
  `actions/setup-go`, `actions/setup-node` and `pnpm/action-setup` for the configured ones (with the toolchains' own
  caches off: L4's per-unit caches serve the gates). On GitLab nothing is rendered; doctor says the image must provide
  them.
- **Go and pnpm in the gate sandbox** (L4-CI-005): a default cache `gobuild` (`GOCACHE`) next to `go` (`GOMODCACHE`),
  and `pnpm` (its store dir). The gates of a repository with `ci.toolchains.go` run with `GOTOOLCHAIN=local` (no
  download of another Go outside `gates.setup`) and `GOFLAGS=-mod=readonly`.
- **Doctor TOOL-001**: the first word of a gate command that is not on the gate PATH is named, with the `ci.toolchains`
  hint (a warning in `l4 doctor --adoption`, an error in a CI run).
- `l4 init` proposes `ci.toolchains` from `go.work`/`go.mod`, `.nvmrc`/`package.json` `engines.node` and
  `packageManager: pnpm@…`.

Out of scope (later stages): TDD red stubs and zero values for Go and TypeScript (the language packs), a native
`go test -json` report, and waiting for the repository's own CI before a plan merge.

## Impact

- `src/l4/config/schema.py` (`CiCfg.toolchains`), `src/l4/config/defaults.py` (caches), `src/l4/ci/github.py` (render),
  `src/l4/sandbox/env.py` (gate env), `src/l4/doctor/` (TOOL-001), `src/l4/init/` (proposals).
- `docs/SPEC.md` (§3.2, L4-CI-005, scenarios, the change row), `docs/quickstart.md`, the skill's `adopt.md`, CHANGELOG.
- No change to the sandbox's guarantees: the toolchains are on the read-only host root; the network rules are the same.
