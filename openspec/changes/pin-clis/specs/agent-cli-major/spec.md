## Purpose

An agent CLI of an unsupported major version is refused by name wherever the harness reads its version, before it
costs a model call. This change extends the gate of `opencode` (L4-OCG-001 to L4-OCG-004) to `kiro-cli`, whose 3.0
changes the default engine and what `KIRO_HOME` holds.

## ADDED Requirements

### Requirement: L4-OCG-005 A kiro-cli of another major than 2 is refused with a named reason
The supported major of the `kiro-cli` adapter SHALL be the major of the pinned `KIRO_VERSION` (2), in
`SUPPORTED_MAJORS` beside `opencode`. Every caller of L4-OCG-001 and L4-OCG-002 SHALL apply it to `kiro-cli --version`
whether or not the profile sets `min_version`: the probe `binary` step SHALL fail without running `auth`, `quota` or
`hello`; doctor ENV-004 SHALL report the profile as failing with the chain severity of a failing CLI, and SHALL fail
closed on a `kiro-cli` whose `--version` holds no version with `kiro-cli reports no version, so its Kiro CLI major
cannot be checked`; doctor LIVE-005 SHALL report it with severity `error` before, and instead of, the recorded-version
comparison. The reason SHALL be
`kiro-cli <version> is Kiro CLI <major>; L4 runs Kiro CLI 2: install kiro-cli <pin> (in CI l4 doctor --ci --fix
installs it; l4 doctor prints the command for this machine); Kiro CLI 3 support comes in a later L4 release`, with the
effective pin (L4-PRV-045). The wording of every OpenCode text SHALL stay unchanged. Under `l4 doctor --ci --fix` a
`kiro-cli` of another major SHALL be `planned` with `found <version> (Kiro CLI <major>), need kiro-cli 2.x (pinned
<pin>)` and replaced by the pin (L4-PRV-042); without `--ci` it SHALL be `manual` with the same reason and the command,
and its files SHALL stay unchanged. After an install, a `kiro-cli` that still reports another major SHALL fail the
action naming the resolved path. `scripts/runner/prereqs.sh` PRQ-12 SHALL report a `kiro-cli` of another major as not
satisfied, naming `Kiro CLI <major>; L4 runs Kiro CLI 2` and the pin.

#### Scenario: SCN-OCG-11 (−) The probe refuses a kiro-cli 3 before any model call
- **GIVEN** a `kiro-cli` profile with no `min_version` and a `kiro-cli` on PATH that prints `kiro-cli 3.0.0`
- **WHEN** the profile is probed
- **THEN** the `binary` step fails with `kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli 2.32.0 …`,
  no `auth`, `quota` or `hello` runs, and the walk goes on to the next profile

#### Scenario: SCN-OCG-12 (−) Doctor makes a kiro-cli 3 an error with the same reason
- **GIVEN** a judge chain whose only profile is a `kiro-cli` profile and a `kiro-cli` on PATH that prints `kiro-cli
  3.0.0`
- **WHEN** `l4 doctor --live` runs
- **THEN** ENV-004 fails with severity `error` naming the profile and the reason, and LIVE-005 fails with severity
  `error` and the reason without printing `unrecorded version`; with a `kiro-cli` that prints no version, ENV-004
  fails with `kiro-cli reports no version, so its Kiro CLI major cannot be checked`

#### Scenario: SCN-OCG-13 (+) CI replaces a kiro-cli 3 with the pin; a person's machine keeps it
- **GIVEN** a regular file `~/.local/bin/kiro-cli` that prints `kiro-cli 3.0.0` on a `linux-x64` machine, a `kiro-cli`
  profile in a role chain, and a fetcher that serves the pinned archive
- **WHEN** `l4 doctor --ci --fix` runs, and on a second such machine `l4 doctor --fix` runs
- **THEN** the first action is `planned` with `found 3.0.0 (Kiro CLI 3), need kiro-cli 2.x (pinned 2.32.0)` and then
  `applied` with `kiro-cli 2.32.0`; the second is `manual` with the same reason and the command, nothing is downloaded
  and the file is unchanged

#### Scenario: SCN-OCG-14 (−) PRQ-12 does not accept a kiro-cli 3
- **GIVEN** `prereqs.sh` and a runner user whose `kiro-cli --version` prints `kiro-cli 3.0.0`
- **WHEN** PRQ-12's check runs
- **THEN** it reports MISSING (check mode) naming `Kiro CLI 3; L4 runs Kiro CLI 2` and `pinned 2.32.0`
