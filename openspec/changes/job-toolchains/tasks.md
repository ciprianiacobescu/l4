Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.
- Name a consumer "a consumer repository".

## 1. Configuration (L4-CI-005)

- [x] 1.1 Tests: `ci.toolchains` loads `go`/`node`/`pnpm` with `version` or `version_file`; SCN-CI-21; the new default
  caches `gobuild` and `pnpm`.
- [x] 1.2 `CiCfg.toolchains` in `config/schema.py`, the cache defaults in `config/defaults.py`, SPEC §3.2.

## 2. Workflow and gate environment (L4-CI-005)

- [ ] 2.1 Tests: SCN-CI-19 (render), SCN-CI-20 (byte-identical without toolchains, for both the action and the copy
  form), SCN-CI-22 (gate env).
- [ ] 2.2 `ci/github.py` renders the steps (pinned shas, caches off); `sandbox/env.py` (or the gate env builder) adds
  `GOTOOLCHAIN=local` and `GOFLAGS=-mod=readonly` when `ci.toolchains.go` is set.

## 3. Doctor and init

- [ ] 3.1 Tests: SCN-CI-23 (TOOL-001), `l4 init` proposes `ci.toolchains` from `go.work`/`go.mod`, `.nvmrc`,
  `package.json` `engines.node` and `packageManager: pnpm@…`.
- [ ] 3.2 Doctor row TOOL-001; the init proposals.

## 4. Docs

- [ ] 4.1 `docs/SPEC.md` (§3.2, L4-CI-005, SCN-CI-19..23, the change row), `docs/quickstart.md`, the skill's `adopt.md`
  (a polyglot repository), `CHANGELOG.md` under a new `## 0.4.13 (unreleased)`.
