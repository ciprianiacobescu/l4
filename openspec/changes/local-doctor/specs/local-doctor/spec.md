## Purpose

A person who runs `l4 doctor` on their own computer learns before a run whether `l4 run` and `l4 verify` can sandbox
there, and nothing in CI changes.

## ADDED Requirements

### Requirement: doctor row LOCAL-001 (amendment of L4-DOC-001's table)
`l4 doctor` without `--ci` SHALL run a row LOCAL-001 of severity warn: it fails with
`l4 run/l4 verify will refuse on this computer: <reason>` when the local preflight (`sandbox_refusal`, L4-SEC-041) would
refuse, the reason being the preflight's (on macOS the ways out), and when `sandbox.mode` is a mode that is not built
(the row names the mode and says it is not built yet, instead of crashing); it passes naming the sandbox a run would
use (`bwrap`, or `none` with `allow_none`). LOCAL-001 SHALL be in the `local` scope only: `l4 doctor --ci` never runs
it, so it never changes a CI job's exit code. Its failure is a warning: the exit code of `l4 doctor` is unchanged.

#### Scenario: SCN-NFR-05 (amended) macOS for local development
- **GIVEN** a developer's macOS machine without bubblewrap
- **WHEN** `l4 doctor` runs
- **THEN** LOCAL-001 warns that `l4 run`/`l4 verify` will refuse here and names the ways out; the exit code is that of
  the other rows; `sandbox.mode: user` is reported by LOCAL-001 as not built yet

#### Scenario: SCN-DOC-10 (+) LOCAL-001 never runs in CI
- **WHEN** `l4 doctor --ci` runs on a host without a sandbox
- **THEN** there is no LOCAL-001 row

#### Scenario: SCN-DOC-11 (+) LOCAL-001 passes where a run can sandbox
- **WHEN** `l4 doctor` runs where the bubblewrap probe succeeds, or with `sandbox.mode: none` and `allow_none: true`
- **THEN** LOCAL-001 passes and names `bwrap`, or `none`

## MODIFIED Requirements

### Requirement: SANDBOX-001 (amendment of L4-DOC-001's table)
The row SHALL say that it is not registered yet (the full probe of L4-SEC-005 is a separate change) and that LOCAL-001
reports a computer that cannot sandbox.

#### Scenario: SCN-DOC-12 (+) No SANDBOX-001 row is printed
- **WHEN** `l4 doctor` or `l4 doctor --ci` runs
- **THEN** no row has the id SANDBOX-001, and the doctor table's SANDBOX-001 entry says it is not registered yet

### Requirement: the artefacts line (amendment of L4-IMP-064's console line)
The suffix "(CI: job artifacts)" SHALL appear only in a CI job (`in_ci_job`); a local run names the two directories only.

#### Scenario: SCN-DOC-13 (+) A local run's artefacts line has no CI suffix
- **WHEN** a run outside a CI job logs its artefacts line
- **THEN** it names the agent and gate directories without "(CI: job artifacts)"; in a GitHub Actions or GitLab CI job
  the suffix (or the not-uploaded note) is as before
