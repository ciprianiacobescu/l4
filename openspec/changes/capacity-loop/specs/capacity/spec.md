## Purpose

A delivery plan never spins on a unit that waits for capacity, and stops for a person when only a fix ends the wait.

## ADDED Requirements

### Requirement: L4-YOLO-035 A capacity wait never chains runs, and a wait only a fix can end stops the plan
A plan step that dispatches its current unit while the unit is `waiting_capacity` SHALL NOT start the next run; the next
schedule, push or person's command SHALL probe again. When the current unit parks in `waiting_capacity` with no profile
of the chain cooling (every failure a missing binary, a failed login or `hello`, a constraint or `serves`), for the same
set of unusable profiles as its previous park with no run of the unit's work between them, the plan SHALL stop with
`capacity_needs_fix`, and the stop SHALL name each profile, its failure, and the fix (the secret or the binary the profile
needs). `l4 yolo resume` SHALL be allowed after that stop. A park with a profile cooling (a limit or credit with a reset)
SHALL keep today's behaviour: the plan waits until `retry_after`.

#### Scenario: SCN-YOLO-90 (−) A failed login does not chain runs
- **GIVEN** an active plan whose current unit parks in `waiting_capacity` because every implementer profile fails its
  `hello` with an authentication error
- **WHEN** the next plan step dispatches the unit and its run parks again
- **THEN** no next run is started by that step

#### Scenario: SCN-YOLO-91 (−) The second identical park stops the plan with the fix named
- **GIVEN** the unit of SCN-YOLO-90 parked twice for the same two profiles, nothing cooling
- **WHEN** the plan step runs
- **THEN** the plan stops with `capacity_needs_fix`, naming both profiles, `opencode authentication failed`, and the fix
  (renew the key the profiles read), and `l4 yolo resume` with a reason goes on

#### Scenario: SCN-YOLO-92 (+) A cooling profile still waits for its reset
- **GIVEN** a unit parked in `waiting_capacity` because the only profile hit a rate limit that resets in 40 minutes
- **WHEN** the plan step runs before the reset
- **THEN** the plan waits (`unit_waiting_capacity`), starts no run, and does not stop
