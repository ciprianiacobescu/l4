## Purpose

A person who answers the question a delivery plan waits for is told what happens next, and the resume they are told
about is not refused.

## ADDED Requirements

### Requirement: L4-YOLO-052 After an answer is pushed, the resume does not refuse it
The plan step, `l4 yolo resume` and `l4 yolo status` SHALL decide by one predicate (`l4.yolo.cycle.still_waits`)
whether the current `awaiting_human` or `clarifying` unit of a waiting plan still waits. When its answers are pushed
and no run has read them, `l4 yolo resume` SHALL resume the plan and start the run that reads them. While a question is
open, the refusal SHALL say that the plan continues by itself at the run that reads the answer, so no resume is needed.

#### Scenario: SCN-YOLO-137 (+) The resume of a waiting plan goes once the answer is pushed
- **GIVEN** a plan `p1` waiting with `unit_awaiting_human`, whose current unit's question Q-003 is answered on the unit
  branch (the unit's next action is `implement`, `answers submitted: Q-003`), and no run has read the answer
- **WHEN** a person runs `l4 yolo resume p1 --reason "answered"`
- **THEN** `plan.resumed` is recorded and a run is started, as the plan step would wake the plan by itself at that run

#### Scenario: SCN-YOLO-138 (−) An open question still refuses the resume, and the refusal says what happens
- **GIVEN** a plan `p1` waiting with `unit_awaiting_human`, whose current unit's question Q-003 is open
- **WHEN** `l4 yolo resume p1 --reason TEXT` runs
- **THEN** it exits 2 with `is still awaiting_human: answer its questions first (l4 questions --unit …)`, says that the
  plan continues by itself at the run that reads the answer, so no resume is needed after it, and writes nothing

### Requirement: L4-YOLO-053 After an answer, the status says what happens next
For a waiting plan whose current unit is `awaiting_human`, the `Next:` line of `l4 yolo status` SHALL say: with a
question open, how to answer it (`l4 questions --unit U`, then `l4 questions answer Q-NNN --unit U --text TEXT`, which
pushes the answer and starts a run) and that the plan continues by itself, naming no `l4 yolo resume`; with the answers
pushed, that the next run reads them and how to start that run now (`l4 yolo resume PLAN --reason TEXT`, or the forge's
start command).

#### Scenario: SCN-YOLO-139 (−) The status of a plan that waits for an answer does not send the person to a resume
- **GIVEN** the plan of SCN-YOLO-138
- **WHEN** `l4 yolo status p1` runs
- **THEN** its `Next:` line names `l4 questions --unit …` and `l4 questions answer Q-NNN --unit … --text TEXT` (which
  pushes the answer and starts a run), says that the plan continues by itself at the run that reads the answer, and does
  not name `l4 yolo resume`

#### Scenario: SCN-YOLO-140 (+) The status after the answer says the next run reads it and how to start it
- **GIVEN** the plan of SCN-YOLO-137 before the resume
- **WHEN** `l4 yolo status p1` runs
- **THEN** its `Next:` line says that the answers of the unit are pushed and the next run reads them, that the plan then
  continues by itself, and how to start that run now: `l4 yolo resume p1 --reason TEXT`, or the forge's start command
  (`gh workflow run l4.yml --ref <base>` on GitHub)
