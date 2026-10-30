## Purpose

A run that exists only to answer the unit's questions answers every question that is due, bounded by time and cost,
and the delegate is told the quote rule it is held to.

## MODIFIED Requirements

### Requirement: L4-DLG-003 (amendment, the questions of one pass)
The pass SHALL ask once per question, oldest first, and MUST NOT ask a decided question again. A pass at the end of a run
in which a step of the unit ran SHALL ask at most `delegate.max_questions_per_run`. A pass in a run in which no step of
the unit ran before it (the run exists for the delegate) SHALL NOT be bound by `max_questions_per_run`: it asks until no
question is due, the soft deadline defers the rest (L4-DLG-013) or a cost limit escalates it (L4-DLG-009). The ledger's
`delegate.pass` (or the existing event that ends a pass) records which bound applied: `cap`, `none_due`, `deadline` or
`cost`.

#### Scenario: SCN-DLG-123 (+) A delegate-only run answers past the cap
- **GIVEN** a unit in `awaiting_human` with 9 open verdict questions, `max_questions_per_run: 5`, and the planner's
  action `delegate`
- **WHEN** the run starts and only the delegate pass runs
- **THEN** the pass asks all 9 (within the cost limits), and the pass's bound is `none_due`

#### Scenario: SCN-DLG-124 (+) The tail of a working run keeps the cap
- **GIVEN** a run whose verify step raised 9 verdict questions
- **WHEN** the delegate pass runs at its end
- **THEN** it asks 5, the bound is `cap`, and the next run is asked for (L4-DLG-007)

#### Scenario: SCN-DLG-125 (−) The soft deadline and the cost cap still bound a delegate-only pass
- **WHEN** the job's remaining time drops under `delegate.timeout` after 4 calls, or the unit's cost cap leaves less than
  one call's cap
- **THEN** the rest is deferred (L4-DLG-013), or escalated with the cost reason (L4-DLG-009), as today

### Requirement: reply checks (amendment of the requirement that lists why a reply is refused)
A `checked` entry whose quote is shorter than `MIN_QUOTE_CHARS` (12, after whitespace is folded) SHALL be refused with
the reason `the quote of <ref> is shorter than 12 characters` (retryable), not `does not resolve`. The delegate's prompt
SHALL state that a quote is at least 12 characters, copied word for word.

#### Scenario: SCN-DLG-126 (−) A short quote is named
- **WHEN** a reply's `checked` entry quotes `'c: {},'` at a line that has it
- **THEN** the refusal reads `checked <ref>: the quote of <ref> is shorter than 12 characters`, it is retryable, and the
  retry's prompt carries that reason; a quote of 12 or more characters that is not on the line keeps `does not resolve`
