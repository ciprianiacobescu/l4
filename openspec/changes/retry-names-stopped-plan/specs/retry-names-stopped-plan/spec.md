## Purpose

An operator who retries a unit that a stopped plan holds learns, from the retry itself, that the plan must be resumed,
and no run is spent on a plan that cannot move.

## ADDED Requirements

### Requirement: A retry names the stopped plan that holds the unit
After a successful `l4 retry`, when a plan that holds the unit is `stopped`, the command SHALL print
`plan <id> is stopped (<stop reason>): the unit runs again after: l4 yolo resume <id> --reason TEXT` and SHALL NOT
start a run on the base branch. In every other case the retry SHALL start the run as before; a failure to read the
plans SHALL NOT fail the retry.

#### Scenario: a halt stopped the plan
- **WHEN** a unit is `halted`, the plan `p1` that holds it is `stopped` with `unit_halted`, and `l4 retry --unit <id>
  --reason r` runs
- **THEN** the unit is retried, the output holds `plan p1 is stopped (unit_halted): the unit runs again after: l4 yolo
  resume p1 --reason TEXT`, no run is started, and the exit code is 0

#### Scenario: an active plan
- **WHEN** the plan that holds the retried unit is `active`
- **THEN** the retry starts a run on the base branch and prints no plan line

#### Scenario: the plans cannot be read
- **WHEN** reading the plan files or states raises
- **THEN** the retry succeeds and starts the run as before
