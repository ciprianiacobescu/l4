## Purpose

A task that the harness ticked without a change of its own is checked against its text by the judge, so that a task
whose criteria were already satisfied, but whose own work was not done, does not pass unseen.

## ADDED Requirements

### Requirement: L4-VER-018 The judge checks each task ticked as already satisfied
The judge prompt SHALL hold a satisfied block when the unit has tasks that the harness ticked as already satisfied.
These are the unit's own tasks, not a fix unit's: the last `task.done` of each, outside any fix-unit context, has
`tdd: already-satisfied`. The block SHALL list, per task, its key, its text from `tasks.md`, the criteria of its last
`task.red_ok` and the `discriminating` tests of each. The system text SHALL ask the judge to answer
`satisfied: [{task, holds, evidence}]`, one entry per listed task. `holds` is true only when the diff or the gate report
shows that the code and documents at head do what the task's text says. `evidence` is the file:line or test id that
shows it, or what is still missing. A prompt with no such task SHALL have no block, and the reply SHALL leave
`satisfied` out.

Each answer SHALL be recorded as `verify.satisfied_judged{task, round, holds, evidence, profile}`. An answer with
`holds: false` SHALL add a major judge finding titled `task <key> is ticked as already satisfied, but its text is not
done`, with the evidence as its detail. It is a judge-only finding, so it goes to a person as L4-VER-013 says. A listed
task that the reply leaves out SHALL be asked for in L4-VER-017's second call, which names it as `satisfied <key>`. A
task still not answered SHALL add the minor finding `the judge did not say whether task <key> is done`, and SHALL be
recorded with `holds: false` and evidence `not answered`. The prompt template version SHALL be 9.

#### Scenario: SCN-VER-72 (+) The judge sees the tasks ticked as already satisfied
- **GIVEN** a unit whose task 3.1 ("add (legacy alias X) to the README table") ended `task.done{tdd: already-satisfied}`
  with criterion C proved by test T, and whose task 1.1 ended `tdd: green`
- **WHEN** the judge prompt is built
- **THEN** it holds a satisfied block that lists 3.1 with its text, C and T, and does not list 1.1; the template is
  `judge@9`

#### Scenario: SCN-VER-73 (−) A task whose text is not done is a major finding
- **GIVEN** the prompt of SCN-VER-72 and a reply with `satisfied: [{task: "3.1", holds: false, evidence: "README.md is
  not in the diff"}]`
- **WHEN** the judge step records the reply
- **THEN** the round has the major judge finding `task 3.1 is ticked as already satisfied, but its text is not done`
  with that evidence, and the ledger holds `verify.satisfied_judged{task: 3.1, holds: false}`

#### Scenario: SCN-VER-74 (+) A task whose text holds adds no finding
- **GIVEN** the prompt of SCN-VER-72 and a reply with `satisfied: [{task: "3.1", holds: true, evidence: "README.md:188"}]`
- **WHEN** the judge step records the reply
- **THEN** no finding names task 3.1, and the ledger holds `verify.satisfied_judged{task: 3.1, holds: true}`

#### Scenario: SCN-VER-75 (−) A task left out is asked for once, then is a minor finding
- **GIVEN** the prompt of SCN-VER-72 and two valid replies that both leave `satisfied` out
- **WHEN** the judge runs
- **THEN** the second call names `satisfied 3.1`, the round has the minor finding `the judge did not say whether task
  3.1 is done`, and no major finding names 3.1
