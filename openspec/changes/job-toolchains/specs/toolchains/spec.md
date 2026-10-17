## Purpose

The L4 job can provide the Go, Node and pnpm toolchains a repository's gates need, so the verifier can gate a polyglot
repository's Go and TypeScript code.

## ADDED Requirements

### Requirement: L4-CI-005 The L4 job provides the toolchains the gates need
The configuration SHALL have `ci.toolchains` with the optional entries `go` (`version` or `version_file`), `node`
(`version` or `version_file`) and `pnpm` (`version`); an entry with neither or both of `version` and `version_file`
SHALL be a load error. For GitHub, the rendered workflow SHALL contain, before the L4 action and in the order go, node,
pnpm, one step per configured entry using `actions/setup-go`, `actions/setup-node` and `pnpm/action-setup` pinned by
commit sha, with their own dependency caches off. For GitLab nothing SHALL be rendered. The default caches SHALL include
`gobuild` (`GOCACHE`) and `pnpm` (the pnpm store directory). With `ci.toolchains.go` set, every gate SHALL run with
`GOTOOLCHAIN=local` and `GOFLAGS=-mod=readonly` unless the gate environment sets them. Doctor row TOOL-001 SHALL name each
gate command whose first word is not on the gate PATH, with the hint to configure `ci.toolchains`.

#### Scenario: SCN-CI-19 (+) The workflow sets up the configured toolchains before L4
- **GIVEN** `ci.toolchains: {go: {version_file: go.work}, node: {version: "22"}, pnpm: {version: "11"}}`
- **WHEN** `l4 upgrade` renders the GitHub workflow
- **THEN** the job has, before the L4 action, a pinned `actions/setup-go` step with `go-version-file: go.work`, a pinned
  `actions/setup-node` step with `node-version: "22"` and a pinned `pnpm/action-setup` step with `version: "11"`, each
  with its cache off

#### Scenario: SCN-CI-20 (+) No toolchains, no steps
- **GIVEN** no `ci.toolchains`
- **WHEN** the workflow is rendered
- **THEN** it is byte-identical to the workflow rendered before this change

#### Scenario: SCN-CI-21 (−) A toolchain entry needs exactly one of version and version_file
- **GIVEN** `ci.toolchains: {go: {}}` or `{go: {version: "1.26", version_file: go.work}}`
- **WHEN** the configuration loads
- **THEN** it is refused with a message naming `ci.toolchains.go`

#### Scenario: SCN-CI-22 (+) Go gates run with the local toolchain and a read-only module graph
- **GIVEN** `ci.toolchains.go` set and a gate `go test ./...`
- **WHEN** the gate runs
- **THEN** its environment has `GOTOOLCHAIN=local`, `GOFLAGS=-mod=readonly`, `GOMODCACHE` and `GOCACHE` under the unit's
  cache

#### Scenario: SCN-CI-23 (−) A gate command that is not on the PATH is named
- **GIVEN** a gate `golangci-lint run ./...` and no `golangci-lint` on the gate PATH
- **WHEN** `l4 doctor --adoption` runs
- **THEN** TOOL-001 warns that `golangci-lint` is not on the gate PATH and names `ci.toolchains`
