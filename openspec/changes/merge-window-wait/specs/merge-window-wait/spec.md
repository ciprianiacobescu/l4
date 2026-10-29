## Purpose

A `merge: auto` plan whose current unit waits only for the hand-off CI window merges in the same CI run when the job
budget allows, instead of idling until a person or the schedule wakes it.

## MODIFIED Requirements

### Requirement: L4-YOLO-013 Stops, waits, cancel and resume
(Amendment, added after "it goes on by itself when the merge is ready.")
When the only cause of `merge_not_ready` is the hand-off window of L4-CI-014 (no CI on H yet), and the step is the plan
step of a CI run whose job budget is known (L4-IMP-012), that names no unit and is not read-only, and
`yolo.merge.require_ci` is false, the step SHALL wait in the run for the rest of the window plus 15 s, at most until the
job's remaining budget less a reserve for the merge, its confirmation and the integration. It SHALL read H's CI about
every 60 s while it waits and stop waiting when CI appears, the window closes or the read fails. After the wait it
SHALL ask the merge guard again from the start, once. When the budget ended the wait before the window closed, the
step SHALL record the wait as above and start the next run once (L4-YOLO-012). A step that did not wait SHALL record
the wait and start no run, as before.

### Requirement: L4-YOLO-012 One plan step per run, and the next run is started
(Amendment) The step that waited for the hand-off window and was cut short by the job budget (L4-YOLO-013) SHALL start
the next run once; that run counts as the step's next run.

### Requirement: L4-CI-014 CI that may not exist yet is running
(Amendment) The read SHALL also give the seconds left of the window (none when no window holds), computed with the same
clock-skew rule as the window itself, so the plan step can wait for it without matching the reason's text.

#### Scenario: SCN-YOLO-122 (+) CI not created yet waits inside the window (amended)
- **WHEN** a `merge: auto` plan's current unit was handed off 4 minutes ago, H has no CI, the window holds, and the run
  is a local run or its job budget is unknown
- **THEN** the step records `plan.waiting{merge_not_ready}` with the window's detail and starts no run, as before

#### Scenario: SCN-YOLO-240 (+) the step waits out the window and merges
- **WHEN** the same unit in a CI run with 40 minutes of job budget left, and no CI appears on H
- **THEN** the step sleeps for the 6 minutes left plus 15 s (in slices of at most 60 s, reading H's CI after each), asks
  the merge guard again, and records `unit.merged{ci: not_run}`; no `plan.waiting` is recorded

#### Scenario: SCN-YOLO-241 (+) CI that appears ends the wait
- **WHEN** during that wait a job of the repository's CI appears on H, running
- **THEN** the wait ends at the next read, and the step records `plan.waiting{merge_not_ready}` naming the unfinished
  job, as for any running CI

#### Scenario: SCN-YOLO-242 (+) a short budget waits what it can and chains one run
- **WHEN** the job budget less the reserve allows 2 of the 6 minutes left
- **THEN** the step waits 2 minutes, records `plan.waiting{merge_not_ready}`, and starts the next run on the target once

#### Scenario: SCN-YOLO-243 (+) a later run waits for the rest and merges
- **WHEN** the plan waits with the window's detail and a CI run with ample budget reaches its step 3 minutes before the
  window closes
- **THEN** `_merge_wait_gone` waits the 3 minutes plus 15 s, the guard can go on, and the step merges the unit

#### Scenario: SCN-YOLO-244 (−) no wait where it cannot be bounded or is not asked for
- **WHEN** the step is read-only (`l4 run --unit`), or `yolo.merge.require_ci` is true, or the base branch requires a
  check that H has not reported, or the run is not in CI
- **THEN** the step never sleeps, and the outcome is the one before this change

#### Scenario: SCN-YOLO-245 (+) the wait reads the window on GitLab too
- **WHEN** a GitLab plan's current unit is handed off and its merge request has no pipeline yet, in a CI run with ample
  budget
- **THEN** the step waits as on GitHub and merges after the window

#### Scenario: SCN-CI-070 (+) the seconds left of the window
- **WHEN** `pr.ready` is 4 minutes before the read, or 1 minute after it (a fast clock), or 2 hours after it (forged)
- **THEN** the seconds left are 360, 600 and none
