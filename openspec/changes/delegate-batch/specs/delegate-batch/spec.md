## ADDED Requirements

### Requirement: L4-DLG-028 The verdict questions of one round share a delegate call
The delegate pass SHALL ask the due verdict questions of one target folder (the unit, or its open fix unit) that have
the same askers in batches of up to `delegate.batch_size` (default 6; 1 asks one question per call), in the pass's order,
within the questions a capped pass may still ask. A question whose blocking tasks or verdict target meets a key of a
question already in the batch, and a question whose previous attempt was a batch call that ended `timeout` or `error`,
SHALL NOT join a batch. Each question SHALL first pass the checks of a single question (still open, its limits, a
question no call can settle, the soft deadline). A batch SHALL be one call with the prompt `delegate-batch@1` and the
result `l4/delegate-batch@1` (`{results: [l4/delegate-result@1]}`); each result SHALL be checked, answered, deferred or
escalated on its own, with its question's own inputs, and a question with no result or two results SHALL be a failed
attempt (deferred with an attempt left, else escalated). A batch of N SHALL need N answers' cost left in the unit's cap
and in the plan's share, SHALL be shortened from its end to fit them and to keep its prompt within `BATCH_MAX_CHARS`,
and SHALL give the adapter a budget of N times `max_cost_usd_per_answer`. The call's cost SHALL be recorded once, each
result carrying its share. A batch of one, and a question of any other kind, SHALL be asked as before (`delegate@7`,
`l4/delegate-result@1`).

#### Scenario: SCN-DLG-127 (+) six verdict questions of one round are one call
- **WHEN** a delegate-only pass has six open verdict questions of the unit, raised by one round, and the defaults
- **THEN** the adapter is called once; six `delegate.asked` carry the same `prompt_sha256` and `batch`; one
  `budget.cost{role: delegate}` holds the call's cost; each `delegate.result` carries a sixth of it; and each answer is
  written and committed on its own

#### Scenario: SCN-DLG-128 (+) each result of a batch stands on its own
- **WHEN** a batch of five gets three results that hold, one whose reference does not resolve, one `escalate`, and no
  result for the fifth question
- **THEN** three questions are answered, the one with the bad reference and the one with no result are deferred to be
  asked again, and the `escalate` is escalated

#### Scenario: SCN-DLG-129 (−) a batch fits the money that is left
- **WHEN** the unit's delegate cap has two answers' cost left and five verdict questions are due
- **THEN** the batch holds two questions and the adapter's budget is twice `max_cost_usd_per_answer`; the next question
  escalates on the unit's cost cap

#### Scenario: SCN-DLG-130 (−) other askers, other kinds and `batch_size: 1` are asked alone
- **WHEN** two verdict questions have different askers; or a technical question is due between verdict questions; or
  `delegate.batch_size` is 1
- **THEN** the questions with different askers are in different calls; the technical question has its own call with
  `delegate@7`; with `batch_size: 1` every question has its own call

#### Scenario: SCN-DLG-131 (−) a batch that timed out is asked question by question
- **WHEN** a batch call of four ends with a timeout
- **THEN** each question is deferred with `batch` recorded, and the next pass asks each of them in its own call

#### Scenario: SCN-DLG-132 (−) a capped pass counts questions, not calls
- **WHEN** seven verdict questions are due at the end of a run in which a step of the unit ran, with
  `delegate.max_questions_per_run: 5`
- **THEN** the pass asks one batch of five, and two questions are left for the next run

#### Scenario: SCN-DLG-133 (−) a batch's prompt is bounded
- **WHEN** the rendered user text of a batch of six is longer than `BATCH_MAX_CHARS`
- **THEN** the batch is shortened from its end until it fits, and the questions left out are asked by a later batch
