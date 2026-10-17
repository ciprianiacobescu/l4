## Purpose

A provider key or a credential value the harness writes to a file for one agent step is readable only inside that
step's own agent sandbox, and no such file outlives its step.

## ADDED Requirements

### Requirement: L4-PRV-040 Credential files are visible only in the step that uses them
The OpenCode provider key file (L4-PRV-028, the custom-provider key) and the credential-loader file (L4-PRV-024) SHALL be
written only in the step's private directory, created with mode 0700, as new 0600 files, and removed when the step
ends, whatever its outcome. That directory lies under the hidden runner cache (L4-SEC-031) and is bound only into its own
step's agent sandbox, so no gate or agent sandbox of another step, unit or project can read the files.

#### Scenario: SCN-PRV-100 (−) A unit's key files are not readable from another unit's sandboxes
- **GIVEN** a working bwrap, unit A's provider key file and credential-loader file written by the real `write_key_file` and `write_credential_file` into A's private directory, and unit B of the same project
- **WHEN** a gate and an agent sandbox of unit B read both files
- **THEN** every read fails, and the files hold their values on the host

#### Scenario: SCN-PRV-101 (+) The private directory is 0700 and the key file is gone after the step
- **GIVEN** an opencode profile with a custom provider and a fake process runner
- **WHEN** an agent step runs once to an end and once to an exception
- **THEN** during the run the private directory and `opencode-config` are 0700 and the key file is 0600, and after each run no key file and no credential file is left

### Requirement: L4-PRV-041 A credential file left by a killed run is removed before the unit runs again
When a workbench is built, the harness SHALL remove a provider key file and a credential-loader file left in the unit's
private directory by a run that was killed, before any agent or gate runs. The probe's `hello` SHALL keep its key in a
new 0700 temporary directory under its working directory, which is the runner cache in a run (hidden, L4-SEC-031) and a
system temp directory in doctor (hidden by the sandbox's own `/tmp`).

#### Scenario: SCN-PRV-102 (−) A key file left by a killed run is gone before the next step
- **GIVEN** `agent-tmp/opencode-config/provider.key` and `agent-tmp/credential` left in a unit's directory
- **WHEN** the next run builds the unit's workbench
- **THEN** both files are gone before the first gate or agent step

#### Scenario: SCN-PRV-103 (−) The hello's key directory is hidden from every sandbox
- **GIVEN** a probe context whose working directory is the runner cache, and a gate spec of any unit
- **WHEN** the hello writes its key and the gate argv is built
- **THEN** the key's directory is under the runner cache, has mode 0700, and the argv covers the runner cache with a tmpfs and binds nothing above or at that directory
