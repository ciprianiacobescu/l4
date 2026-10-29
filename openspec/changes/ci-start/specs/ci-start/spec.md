## ADDED Requirements

### Requirement: L4-OPS-024 `l4 ci start` starts the harness's run only when it is idle
`l4 ci start [--if-idle DURATION]` SHALL start the harness's CI run on the base branch only when the forge shows no run
of it queued or running and, with `--if-idle`, the last one ended at least DURATION ago; it SHALL start nothing and say
why otherwise. It SHALL exit 0 when it started a run or found the forge busy or the last run recent, 3 when the token
is missing, the forge refuses or the forge cannot tell, and 2 for a bad duration.

#### Scenario: SCN-OPS-46 (−) a running run blocks the start
- **WHEN** a run of `l4.yml` on the base branch is in progress
- **THEN** nothing is started, the line says so, exit 0

#### Scenario: SCN-OPS-47 (−) a recent run blocks the start with --if-idle
- **WHEN** `--if-idle 12m` and the last run ended 5 minutes ago
- **THEN** nothing is started, exit 0

#### Scenario: SCN-OPS-48 (+) an idle base starts one run
- **WHEN** `--if-idle 12m`, no run is queued or running, and the last ended 13 minutes ago
- **THEN** one run is started, exit 0

#### Scenario: SCN-OPS-49 (−) a forge that cannot tell starts nothing
- **WHEN** the run listing fails
- **THEN** nothing is started, exit 3

#### Scenario: SCN-OPS-50 (−) a missing token or a bad duration
- **WHEN** no forge token is set, or `--if-idle soon`
- **THEN** exit 3 with the line that says how to start a run, or exit 2
