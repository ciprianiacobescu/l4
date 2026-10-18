## Purpose

A check the harness cannot decide never costs the agent an attempt: the task waits for a person's audited answer, the
plan waits without looping, and the evidence reaches the ledger, the console and the status without job artifacts.

## ADDED Requirements

### Requirement: L4-IMP-063 An inconclusive check holds the task with a harness question
When every unconfirmed criterion of a red step, every corrected test of `test-at-red` or every added test of a test
chore is inconclusive, the harness SHALL discard the step's changes, raise one question of kind `harness` blocking the
task, and end the task `blocked`: no attempt counted, no escalation. An `accept` SHALL let the next attempt count those
criteria when the check is inconclusive again for the tests the question named, labelled `human_override` or
`agent_override`.

#### Scenario: SCN-IMP-312 (−) An inconclusive pre-satisfied check consumes no attempt
- **GIVEN** an already-satisfied red step whose zero-value run ran no test (45 collection errors) and whose base run
  confirms nothing, on a chain of two implementer profiles with `escalate_after: 2`
- **WHEN** the task loop handles the outcome
- **THEN** there is no `task.attempt_failed` and no `implementer.escalated`, one `check.inconclusive` and one
  `question.raised{kind: harness}` name the task, the criteria and the `E` line, the agent ran once, the unit is in
  phase `awaiting_human` with exit 11, and a plan step that sees the unit waits and starts no next run

#### Scenario: SCN-IMP-314 (+) A person accepts the claim on the evidence of the real run
- **GIVEN** the question of SCN-IMP-312 answered `accept: the decorator factory is zeroed by an L4 bug` by a person
- **WHEN** the next run's red step finds the same check inconclusive for the same criteria
- **THEN** the task is committed as already satisfied, each criterion's proof has `via: human_override`, `question`
  and `answer_sha256`, and `check.accepted` and `criterion.pre_satisfied{via: human_override}` are recorded; had
  the second attempt written a different test of the criterion, the answer would not cover it and the task is held
  again; an answer an agent gave records `by: agent` and `via: agent_override`

#### Scenario: SCN-IMP-315 (+) A retry runs the check again
- **GIVEN** the question of SCN-IMP-312 answered `retry: upgraded L4 to the release that keeps decorator factories`
- **WHEN** the next run's red step runs and the zero-value run now confirms every criterion
- **THEN** the task is already satisfied with `proof: pre_satisfied` and no `via`, and the red prompt carried the
  answer's text

#### Scenario: SCN-IMP-305 (−) An inconclusive test-at-red run holds the green step
- **GIVEN** a green step whose test file a person's answer unfroze, and a `test-at-red` run that ran no test
- **WHEN** the green checks finish
- **THEN** the green attempt is not counted, the task is held by a harness question with `check: at_red` that names
  the corrected tests, and the red commit stays

### Requirement: L4-IMP-064 The evidence of a variant run reaches the ledger and the console
`gate.finished` of a failing test gate with no report, no executed test or a collection error, and `task.attempt_failed`,
SHALL carry `excerpt`: its `E` lines and deepest repository location, at most 600 characters, redacted before it is cut,
never read into a prompt. A run that executed no test SHALL NOT print `(expected: …)`, and the artefacts line SHALL say
`not uploaded` when `ci.upload_artifacts` is false in GitHub Actions.

#### Scenario: SCN-IMP-318 (+) The ledger and the console carry the collection error
- **GIVEN** a `test-presatisfied` run that exits 2 with 45 collection errors whose first `E` line is
  `E   TypeError: 'NoneType' object is not callable` and whose message holds a `glpat-` token shape
- **WHEN** the run's events are written and printed in a GitHub Actions job with `ci.upload_artifacts: false`
- **THEN** `gate.finished` has `collection_errors: 45` and an `excerpt` of at most 600 characters with that line and
  the token redacted; the console line reads `gate test-presatisfied fail (exit 2, 0 tests: 0 passed, 0 failed)` with
  no `(expected: …)`, followed by the `check.inconclusive` warning; the artefacts line ends `(not uploaded:
  ci.upload_artifacts is false; the ledger's gate.finished and task.attempt_failed events carry the excerpts)`

## MODIFIED Requirements

### Requirement: L4-IMP-017 A failed attempt, and what does not count
A failed attempt is an attempt that the implementer loop counts against `max_task_attempts`: a harness check that does
not pass, a result failure of L4-IMP-021, or an agent run that ends with a status that is not `ok` and not a limit. It
SHALL count against the profile that ran it. A limit (L4-AVL-006), a `blocked` result, the question about a frozen test
that hangs, and a check held as inconclusive with a `harness` question (L4-IMP-063) MUST NOT count, and MUST NOT start
an escalation. The rest of the requirement (the move to the next profile) is unchanged.

#### Scenario: SCN-IMP-313 (−) An inconclusive check starts no escalation
- **GIVEN** a profile that already failed one red attempt of task 3.1 with `escalate_after: 2`
- **WHEN** its second attempt ends with an inconclusive check
- **THEN** the profile's count stays 1, no escalation is asked, and the task is held

### Requirement: L4-QMD-004 Question ids and the answers of verdict and harness questions
IDs are `Q-NNN`, unique per unit, never reused; `superseded` questions name their successor. A `verdict` answer MUST
start with `accept` or `reject`. A `harness` answer (L4-IMP-063) MUST start with `accept` or `retry`
(case-insensitive), and Status `dismissed` reads as `retry`. Any other answer with Status `answered` is invalid: it is
not consumed, a harness question keeps holding its task, and `l4 plan` and the sticky comment ask for a fix.
`l4 questions accept` SHALL refuse a harness question, and `l4 questions answer` SHALL refuse a harness text that does
not start with `accept` or `retry`.

#### Scenario: SCN-IMP-316 (−) A harness answer must start with accept or retry
- **GIVEN** an open harness question Q-007 holding task 3.1
- **WHEN** a person runs `l4 questions answer Q-007 --unit A --text "looks fine"`, and then writes the same answer by
  hand with Status `answered` and pushes
- **THEN** the command exits 2 with a `Fix:` line naming `accept` and `retry`; after the hand edit `l4 plan` shows
  `harness answer must start with accept or retry: Q-007` and task 3.1 stays held

### Requirement: L4-QMD-009 Agents need the project's consent for a person's decisions
An agent MAY accept or answer a question only when its kind is in `clarifier.auto_accept_kinds`, its kind is not
`verdict` or `harness`, and the effective answer names no frozen path of a task the question holds. Any other write by
an agent MUST be refused unless `clarifier.answer_by_agents` is `true`; both keys are read from `.l4/config.yaml` on
the base branch. For a harness question the refusal SHALL say `a harness override is a person's decision`. The commit
body names the actor.

#### Scenario: SCN-IMP-317 (−) An agent cannot answer a harness question without consent
- **GIVEN** `AI_AGENT=l4-mcp`, no `clarifier.answer_by_agents` on the base, and the open harness question Q-007
- **WHEN** the agent runs `l4 questions answer Q-007 --unit A --text "accept: the run broke"`
- **THEN** it exits 2 with `a harness override is a person's decision` and pushes nothing; with
  `clarifier.answer_by_agents: true` pushed to the base, the same command pushes the answer with `agent: AI_AGENT`

### Requirement: L4-OPS-006 The status names a harness question and its two answers
The `l4 status` table, `l4 status --unit`, `l4 plan` and the waiting detail of a plan are unchanged except for a unit
in `awaiting_human` held by a harness question: the REASON SHALL be `Q-NNN: <title>`; `l4 status --unit` SHALL print
`Cause:` with the check's reason and `Next:` with both answers (`l4 questions answer Q-NNN --unit ID --text "accept:
<why>"`, which takes the claim on the real run's evidence, or `--text "retry: <note>"`, which runs the check again);
`l4 plan` and the plan's waiting detail SHALL say `harness check inconclusive: Q-NNN`. `--json` carries the same
`reason` and `next`.

#### Scenario: SCN-IMP-319 (+) l4 status and the plan name the harness cause and the next step
- **GIVEN** a plan whose current unit A is held by harness question Q-007 on task 3.1
- **WHEN** a person runs `l4 status --unit A`, `l4 plan` and the next plan step runs
- **THEN** `Cause:` quotes the check's reason, `Next:` names both `l4 questions answer Q-007 --unit A --text
  "accept: …"` and `--text "retry: …"`, `l4 plan` shows `harness check inconclusive: Q-007`, and the plan records
  `plan.waiting{reason: unit_awaiting_human}` with that detail
