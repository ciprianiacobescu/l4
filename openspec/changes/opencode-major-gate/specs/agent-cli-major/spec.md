## Purpose

An agent CLI of an unsupported major version is refused by name wherever the harness reads its version, before it
costs a model call. For now this applies to `opencode`, whose v2 binary has the same name and rejects the v1 flags.

## ADDED Requirements

### Requirement: L4-OCG-001 The major version is read from every opencode --version
The harness SHALL derive the major version of an agent CLI from the first version in its `--version` output with one
shared function that accepts both `1.18.34` and `opencode v2.0.32` [V]. The supported major of the `opencode`
adapter SHALL be the major of the pinned `OPENCODE_VERSION` (1). The probe `binary` step, doctor ENV-004, doctor
LIVE-005, `l4 doctor --fix` and `scripts/runner/prereqs.sh` PRQ-11 SHALL compare that major whenever they read an
`opencode --version`, whether or not the profile sets `min_version`. Output that holds no version SHALL stay the
existing "did not report a version" failure.

#### Scenario: SCN-OCG-01 (+) Both version forms give their major
- **GIVEN** the recorded outputs `1.18.34` and `opencode v2.0.32`
- **WHEN** the shared function reads them
- **THEN** it returns 1 and 2, and returns None for text with no version

#### Scenario: SCN-OCG-02 (−) A profile without min_version still has its major checked
- **GIVEN** an `opencode` profile with no `min_version` and an `opencode` on PATH that prints `opencode v2.0.32`
- **WHEN** the probe's `binary` step runs and doctor ENV-004 runs
- **THEN** both fail for the major, and neither passes the profile because no floor was set

### Requirement: L4-OCG-002 An unsupported major fails closed with a named reason
When the major of the `opencode` binary differs from the supported major, the probe `binary` step SHALL fail with
the reason `opencode <version> is OpenCode v<major>; this profile runs v1 (opencode-ai 1.x): install
opencode-ai@<pin> (l4 doctor --fix installs it user-locally); OpenCode 2 support comes in a later L4 release`, and the
`auth`, `quota` and `hello` steps SHALL NOT run. The failure SHALL never be a warning and never `transient`; like
every free-step failure it is not cached. A passing `binary` step's detail SHALL carry `major`. Doctor ENV-004 SHALL
report the profile as failing with the same reason, with the existing chain severity of a failing CLI. Doctor
LIVE-005 SHALL report it as a failure with severity `error` before, and instead of, the recorded-version comparison.
`l4 doctor --live` (LIVE-001) SHALL report the same reason through the probe.

#### Scenario: SCN-OCG-03 (−) The probe refuses a v2 binary before any model call
- **GIVEN** an `opencode` profile and an `opencode` on PATH that prints `opencode v2.0.32`
- **WHEN** the profile is probed
- **THEN** the `binary` step fails with the named reason, no `hello` runs, and the walk goes on to the next profile

#### Scenario: SCN-OCG-04 (−) ENV-004 fails the chain whose only opencode profile is v2
- **GIVEN** an implementer chain whose only profile is an `opencode` profile and a v2 `opencode` on PATH
- **WHEN** `l4 doctor` runs
- **THEN** ENV-004 fails with severity `error`, naming the profile and the reason

#### Scenario: SCN-OCG-05 (−) LIVE-005 makes a wrong major an error, not an unrecorded-version warning
- **GIVEN** a judge chain with an `opencode` profile and a v2 `opencode` on PATH
- **WHEN** `l4 doctor --live` runs LIVE-005
- **THEN** LIVE-005 fails with severity `error` and the named reason, and does not print `unrecorded version`

### Requirement: L4-OCG-003 A run or hello rejected for a v1 flag is unsupported_version
`FailureClass` SHALL gain `unsupported_version`. A hello whose exit code is not 0 and whose stderr matches
`Unrecognized flag: --(pure|dir)\b` [V] SHALL fail with the class `unsupported_version` and a reason beginning
`unsupported_version:`. That class SHALL NOT be remembered in the probe cache: only `other` and `auth` are, so
installing v1 takes effect at the next probe. A run SHALL read the tail (the last 8 KiB) of its stderr file. A run
whose exit code is not 0, that has no `error` event, and whose stderr matches the same pattern SHALL end with status
`error` and a detail beginning `unsupported_version:`. It SHALL never be marked retryable.

#### Scenario: SCN-OCG-06 (−) The recorded v2 rejection of --pure is unsupported_version at the hello
- **GIVEN** the recorded v2 stdout (the run help) and stderr (`Unrecognized flag: --pure in command opencode run`),
  exit 1
- **WHEN** the opencode hello evaluates them
- **THEN** it fails with class `unsupported_version`, not `transient`, and the probe cache holds no entry for it

#### Scenario: SCN-OCG-07 (−) The same rejection in a run is a named error
- **GIVEN** the recorded v2 stdout and the `--dir` stderr as a run's raw events and stderr file, exit 1
- **WHEN** the adapter parses the run
- **THEN** the status is `error` and the detail begins `unsupported_version:` and names `opencode --version`

### Requirement: L4-OCG-004 Provisioning replaces a wrong major with the pinned v1
`l4 doctor --fix` SHALL treat an `opencode` whose major differs from the supported major as not satisfied. It SHALL
plan the pinned install with the reason `found <version> (OpenCode v<major>), need opencode-ai 1.x (pinned <pin>)`,
install into the harness's npm prefix, and link `~/.local/bin/opencode`. The agent link step of a gated adapter
SHALL NOT replace an existing path that is not a symlink: the action fails and names the path and the manual command.
The other links the harness makes (Node, `laya-serve`, other agents) SHALL keep their current behaviour. After the install, the major
of the `opencode` the harness path resolves SHALL be checked, and a wrong one fails the action naming the resolved
path. `scripts/runner/prereqs.sh` PRQ-11 SHALL pass only an `opencode` of major 1 at least the pin. A v2 still first
on the runner's login PATH after the apply SHALL be reported FAILED with its path. PRQ-15 SHALL run `opencode
models` only when PRQ-11's check passes.

#### Scenario: SCN-OCG-08 (+) doctor --fix installs v1 where v2 was present
- **GIVEN** a v2 `opencode` on the harness path and an `opencode` profile in a role chain
- **WHEN** `l4 doctor --fix` plans and applies
- **THEN** the action is `planned` with the named reason, then `applied` with `opencode 1.18.34`, and the harness path
  resolves the v1 link

#### Scenario: SCN-OCG-09 (−) A regular file at the link path is never replaced
- **GIVEN** a regular file (not a symlink) at `~/.local/bin/opencode` that prints `opencode v2.0.32`
- **WHEN** `l4 doctor --fix` applies the install
- **THEN** the file is unchanged, and the action is `failed`, naming the path and the manual command

#### Scenario: SCN-OCG-10 (−) PRQ-11 does not accept OpenCode v2
- **GIVEN** `prereqs.sh` and a runner whose `opencode --version` prints `opencode v2.0.32`
- **WHEN** PRQ-11's check runs
- **THEN** it reports MISSING (check mode) with the version, the path and `need 1.x >= 1.18.34`, and PRQ-15 does not
  run `opencode models`
