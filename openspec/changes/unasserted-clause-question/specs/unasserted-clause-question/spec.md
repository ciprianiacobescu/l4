## ADDED Requirements

### Requirement: L4-IMP-095 A clause a step leaves unasserted is asked before the task goes on, and the judge checks it
The result object (L4-IMP-005) SHALL have the optional property `unasserted`: an array of at most 3 objects, each with
the required `criterion` (a string with the pattern of `criteria_ids`), `clause` (a string of 1 to 300 characters: the
clause of the criterion's scenario, quoted) and `why` (a string of 1 to 300 characters). The file-result schema
(L4-IMP-019) SHALL keep it, and the strict schema of a native adapter (L4-FAC-009) SHALL make it nullable, `null`
meaning absent. The normalization (L4-IMP-020) SHALL lower the hex digits of a criterion id, drop an `unasserted` that
is not an array and an item that does not hold that shape (a criterion id is matched whole: a trailing newline, an
annotation such as `C-1a2b3c4d (Req 1.2)` and an alias such as `Req 1.2` do not hold it), cut the items after the third,
and cut a `clause` or `why` over its limit with the cut marker, each recorded as a fix; it SHALL NOT add an entry. The
red template SHALL tell the agent to list there each clause of a scenario the task cites that its tests leave
unasserted, for any reason, and the green template each value or behaviour of a cited scenario that its code would have
to choose and the spec does not settle; both SHALL say not to say it only in `notes_for_verifier`, and that a step that
lists a clause no answer of the task settles is not kept. The harness SHALL NOT read the words of `notes_for_verifier`
or `summary` as such a list.

A step whose normalization dropped an `unasserted` item (or the whole list), or one of whose entries names a criterion
id that is not one of the unit's criteria, SHALL be a failed attempt, whatever its status: nothing of the step is kept,
it is counted as an invalid result is (`task.attempt_failed` with the reason `the agent's result is invalid:
<problems>`, bounded by `implementer.max_task_attempts` and subject to the escalation rules), no question is raised, and
the next prompt carries an excerpt that names each problem (`unasserted item 2 has no why`, `unasserted: C-99999999 is
not one of this unit's criteria`) and the unit's criterion ids. Such a step SHALL NOT be a `blocked` step, and a step
that fails for another reason SHALL NOT become one by listing an id that is not the unit's.

An entry SHALL be *settled* when the unit's ledger holds a `question.raised` of the same task and fix unit (or of none)
whose `clause.criterion` is the entry's criterion and whose `clause.text_sha` is the hash of that criterion's text as
the unit has it now, and that question is answered (L4-QMD-005); the newest such question settles it. Any other entry
SHALL be *new*, so an answer given before the scenario's body was edited (a criterion id hashes the scenario's name, not
its body) settles nothing. When a red, green or single step lists a new entry, the harness SHALL handle it as a
`blocked` step (L4-IMP-008, L4-IMP-021), whatever its status: nothing of the step is kept, it is not a failed attempt,
and the harness SHALL raise the result's own questions and then one question per new entry, in order, of kind
`ambiguous`, with Blocking tasks the task, the criterion on its Criteria line, the title `Task <k> (<phase>) left a
clause of <criterion> unasserted: <clause>`, and a context that quotes the clause and the reason and says that the step
was not kept and that the next step of the task reads the answer. Each such question SHALL be recorded as
`question.raised{..., clause: {criterion, phase, text_sha}}`. A `blocked` result with a new entry and no question of its
own SHALL NOT also get the question made from its summary. The question SHALL hold the task as any implementer question
does: the task stays pending, so the unit goes to the clarifier or to `awaiting_human` and SHALL NOT reach verification
while the question is open; the delegate answers it where the unit is in its scope and `ambiguous` is in
`delegate.kinds`; and the next step of the task reads the answer (L4-CLR-006).

A step whose entries are all settled SHALL be judged as today, and its `task.red_ok`, or the `task.done` of a green or
single step, SHALL record them as `unasserted: [{criterion, clause, why, question}]`, the texts redacted, with
`question` only when the settling question has an answer (answered, accepted or answered by the clarifier): a dismissed
question settles the entry and is not named. Every judge prompt of a round SHALL carry, in its user text after the
answers and before the implementer's hint, the section `## Clauses the implementer's tests do not assert (check each
against the code)` with the harness's instruction and a data block of one line per recorded entry whose criterion the
prompt judges, `<criterion> task <k> (<phase>): "<clause>" | why: <why> | answer: <question>` (`answer: (dismissed)`
when the entry records no question; `<k>` and the question id are `<fix unit>/<k>` and `<fix unit>/Q-NNN` for a fix
unit's, as the done tasks and the answer blocks name them; a `|` in the clause or the reason is written `\|`), at most
6,000 characters together, the lines past that counted in a last line `(+N clauses not shown)`; its length SHALL be
charged to the judge's context budget before the spec text. The instruction SHALL say that the criterion was asked and
the answer, when one is named, is among the answers above, that a passing test does not show a listed clause, that the
judge reads the code for each and judges its criterion as the clause and the named answer read (L4-VER-066), failing it
with the clause named when the code does not do it, and that the clause and the reason are the implementer's words. A
prompt with no such entry SHALL have no section. The judge's system text and `judge@13` SHALL NOT change, and the
`notes_for_verifier` block SHALL keep its text and place.

#### Scenario: SCN-IMP-510 (+) a red step that lists an unasserted clause is not kept and asks about it
- **WHEN** task 1.1 cites `C-1a2b3c4d` (`WHEN an entry is skipped THEN its action is recorded`), and its red step writes
  a failing test and reports status `done` with `unasserted: [{criterion: "C-1a2b3c4d", clause: "its action is
  recorded", why: "the spec does not say which action"}]`
- **THEN** nothing of the step is committed and no `task.attempt_failed` is recorded; `questions.md` gets one open
  question of kind `ambiguous`, Blocking tasks `1.1`, Criteria `C-1a2b3c4d`, titled `Task 1.1 (red) left a clause of
  C-1a2b3c4d unasserted: its action is recorded`, whose context quotes the clause and the reason;
  `question.raised{kind: ambiguous, task: "1.1", clause: {criterion: "C-1a2b3c4d", phase: "red"}}` is recorded; and the
  unit ends `awaiting_human` with exit 11 (after the clarifier, when one is configured, leaves the question open)

#### Scenario: SCN-IMP-511 (+) the answer reaches the next step, and the criterion is not asked again
- **WHEN** the question of SCN-IMP-510 is answered `null: the other capability's spec sets it to null`, and the next
  run runs task 1.1
- **THEN** the red prompt carries the answer block; a red step that asserts the clause is committed as usual; and a red
  step that lists a clause of `C-1a2b3c4d` again, in any words, raises no new question and is committed when its checks
  pass, with `task.red_ok.unasserted: [{criterion: "C-1a2b3c4d", clause: …, why: …, question: "Q-001"}]`

#### Scenario: SCN-IMP-512 (+) a green step that would decide what the spec does not settle is not kept
- **WHEN** task 1.1's red is committed and its green step reports status `done` with `unasserted: [{criterion:
  "C-1a2b3c4d", clause: "its action is recorded", why: "I chose continue; the spec does not say"}]`
- **THEN** the worktree goes back to the red commit, the task is not ticked, one `ambiguous` question titled `Task 1.1
  (green) left a clause of C-1a2b3c4d unasserted: its action is recorded` holds 1.1, and once it is answered the task
  resumes at green with the answer in its prompt

#### Scenario: SCN-IMP-513 (+) the unit does not reach verification while the question is open
- **WHEN** the question of SCN-IMP-510 is open, every other task of the unit is done, and a run starts
- **THEN** no step of task 1.1 runs, no verification round starts, the unit stays `awaiting_human` with exit 11, and
  with `delegate.enabled` and the unit in scope the delegate pass asks that question

#### Scenario: SCN-IMP-514 (−) a malformed or excess entry is dropped or cut, and a dropped one fails the attempt
- **WHEN** a result's `unasserted` holds an item without `why`, an item whose `criterion` is `C-XYZ`, and four
  well-formed items, the first of which has a clause of 400 characters
- **THEN** `result.normalized` records `{field: unasserted, fix: dropped, count: 2}`, `{field: unasserted, fix: cut,
  count: 1}` and `{field: unasserted.clause, fix: cut, length: 400}`; three entries are left, and the long clause ends
    with `[cut by L4: … characters removed]` within 300 characters; and the step is a failed attempt, not a kept one:
  `task.attempt_failed` with the reason `the agent's result is invalid: unasserted item 1 has no why; unasserted item 2
  has criterion "C-XYZ" that is not a criterion id (...)`, nothing of the step kept, no question raised, and the next
  prompt names both items. The same holds for an item with an empty `why` or `clause`, an annotated id `C-1a2b3c4d (Req
  1.2)`, an alias `Req 1.2` and an id with a trailing newline; a criterion `C-1A2B3C4D` is read as `C-1a2b3c4d` (a fix
  `{field: unasserted.criterion, fix: replaced, count: 1}`) and kept

#### Scenario: SCN-IMP-515 (−) the words of a note are not a signal
- **WHEN** a red step's `notes_for_verifier` says `I did not assert entry.action, because the spec text is ambiguous
  there` and its result has no `unasserted`
- **THEN** the step is judged as today and committed when its checks pass, no question is raised, and the judge sees
  the note in the hint block only

#### Scenario: SCN-IMP-516 (+) the judge gets the recorded clauses as a list to check
- **WHEN** the unit's ledger holds the `task.red_ok.unasserted` entry of SCN-IMP-511 and the judge prompt of a round is
  built
- **THEN** it has the section `## Clauses the implementer's tests do not assert (check each against the code)`, after
  the answers and before the implementer's hint, whose data block has the line `C-1a2b3c4d  task 1.1 (red): "<clause>" |
  why: <why> | answer: Q-001`; a batch or follow-up prompt that does not judge `C-1a2b3c4d` has no such line; a unit
  with no entry has no section; the system text is unchanged and the version is `judge@13`. An entry whose question was
  dismissed is recorded without `question` and its line ends `| answer: (dismissed)`, the instruction says the answer
  is named only when there is one, a fix unit's entry names its task as `<fix unit>/1.1`, and a `|` in the clause or
  the reason is written `\|`, so a clause cannot fake an answer

#### Scenario: SCN-IMP-517 (+) the strict and the file schemas carry the field
- **WHEN** the strict copy of the canonical schema is made for Codex, and the file-result schema is derived
- **THEN** in the strict copy `unasserted` is a nullable array of at most 3 objects with `additionalProperties: false`
  and the required `criterion`, `clause` and `why` (the last two of 1 to 300 characters), a reply with `"unasserted":
  null` parses with no entry, and the file-result schema has the property as the canonical schema has it

#### Scenario: SCN-IMP-518 (+) the red and green prompts say when to fill the field
- **WHEN** the red and green prompts are rendered
- **THEN** the red prompt says to list in `unasserted` each clause of a cited scenario that its tests leave
  unasserted, for any reason, the green prompt says to list a value or behaviour it would have to choose that the spec
  does not settle, both say that such a step is not kept, and the versions read `contract@13+red@14` and
  `contract@13+green@7`, which the template lock holds

#### Scenario: SCN-IMP-519 (−) a blocked result raises its own questions first, and a fix unit asks in its own file
- **WHEN** a red result has status `blocked`, one question of its own and one new entry; and in turn a fix unit's task
  step lists a new entry
- **THEN** two questions are raised, the result's own first, and no `Task 1.1 is blocked` question; the fix unit's
  question is in the fix unit's `questions.md`, holds the fix unit's task, and its `question.raised` carries `fix_unit`.
  Two cases are not asked as before: a step that lists a well-formed criterion id that is not one of the unit's (four
  runs with four different ids) is a failed attempt each time, counted against `max_task_attempts` and escalated, with no
  question, and a failing step that lists such an id stays failed; and an entry whose question was answered before the
  body of its scenario was edited (the id stays, `question.raised.clause.text_sha` differs) is new and asked again
