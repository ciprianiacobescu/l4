## Context

An implementer step ends with a result object (L4-IMP-005). `tdd.agent_step` finds it, normalizes it (L4-IMP-020,
`normalize.normalize`), validates it (`result.parse_result`) and returns `StepOutcome("blocked", result)` when the status
is `blocked`, else `StepOutcome("ok", result)` after the secret scan. `run_red`, `run_green` and `run_single` discard the
step's changes on a `blocked` step (green back to the red commit) and hand its `questions` to `loop._run_task`, which
calls `loop._raise_blocked`: `_questions` binds each to the task (`blocking_tasks = (task.key,)`; a `blocked` result
with no question gets one `ambiguous` question made from its summary), `raise_questions` writes them to the unit's
`questions.md`, `question.raised{id, task, kind, title, profile...}` is recorded, the file is committed and pushed, and
the task returns `TaskOutcome("blocked")`. The orchestrator then sends the ids to the clarifier when one is available,
else parks the unit in `awaiting_human` (exit 11). A `done` result's `questions` are never read.

A question *holds* the pending tasks its Blocking tasks line names until it is answered (L4-QMD-005, `questions.holds`).
Everything that decides whether a unit can go on reads that: `select_next_step` skips a held task, `questions_hold`
parks the unit when every pending leaf is held, `ALL_LEAVES_DONE` (the edge to `implemented` and so to verification)
is taken only when no pending task is left, `answers_unblock` frees the task once its question is answered, the
delegate takes only the open questions that hold a pending task or are verdict questions (`due.held_ids`), the fix loop
does the same for a fix unit's tasks (`fixloop`, `open_blocking_questions`), and the next step of the task reads every
answered question that holds it (`tdd._answers`, L4-CLR-006). A question whose task is done holds nothing.

The judge reads the implementer's words only through `ladder._notes`: the `notes` of every `task.red_ok` and
`task.done`, joined and cut at `MAX_NOTES_CHARS` (6,000), in the last block of its user text, headed `Hint from the
implementer (UNVERIFIED: it may be wrong or self-serving; check it against the diff)`. It reads the family's answered
technical, product and ambiguous questions as answer blocks (L4-VER-065) and judges a criterion as an answer narrowed it
(L4-VER-066). A section of the user text with its own instruction can be added without a change of the system text:
`## Named tests changed in place` did so (L4-VER-068, `judge@13` unchanged).

## Goals / Non-Goals

**Goals:** a step that leaves a clause of a cited scenario unasserted, or would decide a value the spec does not
settle, says so in a structured field; the harness asks about each such clause before the task goes on, so the answer
reaches the code before the merge; the judge is given the clauses that a committed step still left unasserted as a list
to check; no keyword in free text is read.

**Non-Goals:** reading `notes_for_verifier` or `summary`; raising the `questions` of a `done` result; a change of the
contract, the output section, the single-phase templates or the judge's system text; a change of what holds a task, of
the clarifier's routing or of the delegate's kinds and scope; a hold of verification by an open question whose task is
done.

## Decisions

### D1. The field `unasserted`

The canonical schema `l4/implementer-result@1` (the packaged `implementer-result.schema.json`, its fixture
`tests/fixtures/schemas/implementer-result.schema.json`, and the JSON block of SPEC 7.4) gains, after `questions`:

```json
"unasserted": {"type": "array", "maxItems": 3, "items": {
  "type": "object", "required": ["criterion", "clause", "why"],
  "properties": {"criterion": {"type": "string", "pattern": "^C-[0-9a-f]{8}$"},
                 "clause": {"type": "string", "maxLength": 300},
                 "why": {"type": "string", "maxLength": 300}}},
  "description": "clauses of the cited scenarios that this step's tests or code leave unasserted or undecided, for any reason; a step that lists one is not kept, and each becomes a question that holds the task"}
```

- `maxItems: 3` as `questions` has: a step with more clauses lists three, and its next attempt (after the answers) the
  rest. `maxLength: 300` for the clause and the reason, as a suppression's `reason` has; the question's context quotes
  both, so they must stay short.
- The model: `Unasserted(_Open)` with `criterion: str`, `clause: str`, `why: str`; `ImplementerResult.unasserted:
  list[Unasserted] = []`.
- The file-result schema (`_file_schema`) pops only `phase`, `task_ids`, `files_changed` and `tests_added`, so it keeps
  the field with no change of code; the prompt-contract `# Output` section shows it inside the schema it prints.
- The strict copy for Codex (`strictify_schema`, L4-FAC-009) makes every property required and the optional ones
  nullable: `unasserted` becomes `{"type": ["array", "null"], ...}` and each item gets `additionalProperties: false`
  with its three required keys; `drop_nulls` reads `null` as absent, as for every optional property. Nothing in
  `codex.py` changes. The recorded strict schema of Codex 0.160.0 (`tests/fixtures/recorded/codex/0.160.0/
  implementer-result.strict.schema.json`) is what that version was given and stays as recorded: the test that compares
  it with `strictify_schema(CANONICAL)` compares it with the strict copy less the new property, and a new assertion
  checks the new property's strict form. The recorded replies, which have no `unasserted`, stay valid against the
  recorded schema and against the canonical one.
- The normalization (L4-IMP-020) gains one rule, `_unasserted`, among the drops and the cuts: an `unasserted` that is
  not a list is dropped (`{field: "unasserted", fix: "dropped"}`); an item that is not an object with a `criterion`
  string of the pattern, a string `clause` and a string `why` is dropped (`count`); after three items the rest are cut
  (`{field: "unasserted", fix: "cut", count}`); a `clause` or `why` over 300 characters keeps its start and ends with
  the cut marker (`{field: "unasserted.clause"` or `"unasserted.why", fix: "cut", length}`). The limits are read from
  the schema, as the others are. The normalization never adds an entry.

*Alternative rejected:* read words of `notes_for_verifier` (`ambiguous`, `unclear`, `did not assert`). A test can show
that a note with the word is caught, never that a note without it means nothing is open, and prose that quotes the word
("the spec is unambiguous") misfires. The field is the agent's explicit statement; a step that writes only a note is
judged as today (SCN-IMP-515).

### D2. New and settled entries

An entry is *settled* when the unit's ledger (`_answer_events(wb)`: the run's ledger, and a fix unit's own) holds a
`question.raised` whose `task` is the step's task, whose `fix_unit` is the step's (`wb.event_context.get("fix_unit")`,
or absent for both), and whose `clause.criterion` is the entry's criterion, and whose question in the step's
`questions.md` is answered (`is_answered`: answered, accepted, answered by the clarifier, dismissed). Its question is the
newest such one. Every other entry is *new*. `clauses.split_clauses(wb, task, entries) -> Split(new, settled)`, with
`settled` as `(entry, question_id)` pairs, is the one place this is decided.

The key is the task and the criterion, not the clause's text. A clause re-quoted in other words, or a second clause of
the same criterion found by a later step, is settled by the first answer, so the task asks about a criterion once and
the loop "list, ask, answer, list again" is bounded by the task's criteria. What a later entry adds is not lost: it is
recorded and shown to the judge (D5). A text key (the hash of the normalised clause) was rejected for that reason: an
agent that re-quotes a clause differently after the answer would park the unit again, and nothing else bounds it (a
`blocked` step is no failed attempt, D3).

Only an answered question settles. An open one cannot meet a running step of its task (it holds the task), and if it
did (a person resumed by hand), asking again is the safe side: it never lets a step pass with the question open. A
question superseded by `l4 restart` is gone with its ledger, so the clause is asked again in the new attempt.

### D3. A step with a new entry is a `blocked` step

In `agent_step`, after `parse_result` and before the secret scan, `split_clauses` runs on `result.unasserted`. When the
status is `blocked` or `new` is not empty, the step returns `StepOutcome("blocked", result, dropped_questions=...,
clauses=new)`, whatever the status said. `run_red`, `run_green` and `run_single` already discard a `blocked` step's
changes (red to its base, green to the red commit, as L4-IMP-008 says) and return their `blocked` outcome, which now
carries `clauses` too; `_run_task` passes them to `_raise_blocked`. It is not a failed attempt: no `task.attempt_failed`,
no count against `max_task_attempts`, no escalation, as for any `blocked` step.

`_questions(task, questions, summary, asked, ..., clauses=())` gives the result's own questions first, as today, then
one per new entry from `clauses.clause_question(task, phase, entry, criteria)`:

- kind `ambiguous`; Blocking tasks: the task; `criteria`: the criterion when it is one of the unit's
  (`wb.provider.criteria(wb.ref)`), so `questions.md` shows it on the `Criteria:` line;
- title `Task <k> (<phase>) left a clause of <criterion> unasserted: <clause>` (one line; `questions.md` cuts a title at
  200 characters);
- context:

  ```
  The <phase> step of task <k> did not assert this clause of <criterion>, and listed it in `unasserted`:

  > <clause>

  Its reason: <why>

  The step was not kept. Answer with what the clause means for this task: the value or behaviour the code must have,
  or that it stays unasserted. The next step of the task reads the answer, and the judge checks the code against it.
  ```

  with `<criterion> is not one of this unit's criteria.` after the quote when the id is not the unit's (the entry is
  still asked: a wrong id is the agent's mistake, and the clause may be a real gap);
- no options.

The summary question (`Task <k> is blocked`) is made only when there is neither a question of the result nor a new
entry. `_raise_blocked` records each entry's question as `question.raised{..., clause: {criterion, phase}}` (the
workbench adds `fix_unit`), which is what D2 reads. The clause and the reason are the agent's text: `questions.md`
redacts and escapes them as it does every context (`_block`), and the event holds no text of the agent beyond the title,
as today.

### D4. Blocking decision: the question holds the task

Three choices were weighed, against the existing question lifecycle.

**Blocks the task (chosen).** The question names the task under Blocking tasks, and the task is still pending: red's
step was not committed, or green's was not (the green commit is the one that ticks the task). So every rule of the
Context applies with no new code: `select_next_step` skips the task, `questions_hold` parks the unit, `ALL_LEAVES_DONE`
cannot be taken while the task is pending, so the unit cannot reach verification, let alone a merge, while the question
is open; the clarifier is asked first when one is available, and it never auto-answers an `ambiguous` question unless the
project put the kind in `clarifier.auto_accept_kinds` (L4-CLR-002); the delegate takes the question at the end of the run
where the unit is in its scope and `ambiguous` is in `delegate.kinds` (the default), and starts the next run
(L4-DLG-003, L4-DLG-007); a person answers it with `l4 questions answer`; `answers_unblock` frees the task; the task's
next step reads the answer in its prompt; a fix unit's question holds the fix unit's task through the fix loop's own
`blocked_tasks`. In the live case the red step would have asked about `entry.action`, the delegate (which reads the
repository) or a person would have answered with the other capability's `null`, red would have asserted it, and green
would have had no value to choose.

**Blocks only verification.** The task would go on (green chooses a value) and the unit would wait for the answer
before verification. Nothing does that today: an open question whose task is done holds nothing, so the orchestrator,
`answers_unblock` (it needs a pending task the answer frees), the delegate's `held_ids`, the planner's facts, `l4
status` and the fix loop would each need a new rule for a question that holds the unit and no task. And the answer
would still come after green: when it differs from green's choice, the judge fails the criterion and a fix unit
changes the code, the round the live case paid for.

**Blocks nothing.** The judge alone would have to catch it, from a list instead of a note. The live judge passed with
the note in front of it; nothing makes a list a guarantee. Rejected: it does not meet the goal.

**Commit red, then hold the task before green** (a variant of the first) keeps red's tests, but leaves the answered
clause without a red test, so the judge is the only check of it; and it cannot apply to green, whose commit ticks the
task. Discarding the step instead gives one rule for every phase, the one `contract.md` already asks of the agent
("change nothing and report status blocked"), and after the answer red writes the test that asserts the clause. The
cost is one step run again, red's (tests only) or green's (discarded as any `blocked` green is: `discard_changes`
resets to the red commit and deletes the unit's WIP ref).

### D5. Settled entries are recorded, and the judge checks them

A step whose entries are all settled goes on as today. The event that carries the step's notes records them as
`unasserted: [{criterion, clause, why, question}]`, the settled entries in the result's order, `clause` and `why`
redacted with `wb.redactor.redact_text` (each at most 300 characters already); an empty list is not written. Those
events are `task.red_ok` (both emits in `run_red`: the red commit and the already-satisfied commit; the
already-satisfied `task.done` that follows repeats its notes and does not repeat the entries), the `task.done` of
`run_green`, and the `task.done{tdd: "exempt"}` of `run_single`. The `task.done` of an accepted repair (L4-IMP-091)
writes no notes, because the saved result is not what the person read, and writes no entries either. `split_clauses` is
called again where the event is written, so a replayed held step (L4-IMP-065), which does not pass through
`agent_step`, records the same; an entry that is no longer settled there (its question was superseded meanwhile) is
recorded without `question`.

`ladder._clauses(events) -> list[ClauseRef]` reads those records from the same events `_notes` reads, in ledger order,
one `ClauseRef(task, phase, criterion, clause, why, question)` per entry; `phase` is `red` for a `task.red_ok`, `single`
for a `task.done` with `tdd: "exempt"`, else `green`. `build_judge_prompt` gains `clauses: Sequence[ClauseRef] = ()`
and renders, after the answers block and before the implementer's hint, for the entries whose criterion is one of the
prompt's `criteria` (a part, a batch and a follow-up each judge their own criteria):

```
## Clauses the implementer's tests do not assert (check each against the code)
The implementer said its tests leave these clauses of the criteria unasserted, and each was asked as a question; the
answer named is among the answers above. A passing test does not show a clause listed here: read the code for each,
judge its criterion as the clause and that answer read, and fail the criterion, naming the clause, when the code does
not do it. The clause and the reason are the implementer's words; the criterion's text is the spec.
<l4:data source="unasserted clauses">
C-1a2b3c4d  task 1.1 (red): "the entry's action is null" | why: the spec does not say which value | answer: Q-004
</l4:data>
```

The lines together are at most `MAX_CLAUSES_CHARS = 6_000`; the lines past it are left out and counted in a last line
`(+N clauses not shown)`. A prompt with no such entry has no section, so every prompt of a unit without entries is
byte for byte today's. The block's length is charged to the judge's context budget before the spec text, with the
criteria, the done tasks and the answers (`plan_context(fixed_chars=...)`). The system text and `judge@13` do not change
(the instruction is in the user text, as `## Named tests changed in place` has it). The notes block keeps its text and
place: it is still the implementer's unverified hint; the list is the harness's statement of what the tests do not show.

### D6. The templates say when to fill the field

`red.md` (version 13 to 14) gets, after the rule on other existing tests:

> Assert every clause of each scenario this task cites. If your tests leave a clause unasserted, for any reason (the
> spec does not settle what it means, it contradicts another scenario or the current code, or a test cannot observe
> it), list it in `unasserted`: the criterion id, the clause quoted word for word from the criterion, and why; at most
> 3 entries. Do not say it only in `notes_for_verifier`. A step that lists a clause that no answer of this task settles
> is not kept: the harness asks about each listed clause and the step runs again with the answers, so you may stop as
> soon as you know. Where an answer of this task settles a clause, assert it as the answer reads.

`green.md` (version 6 to 7) gets, after the binding-decision rule:

> If a scenario this task cites leaves a value or behaviour open that your code would have to choose (the spec does not
> settle it and the red tests do not assert it), do not choose it: list it in `unasserted` (the criterion id, the clause
> quoted word for word from the criterion, and why; at most 3 entries), or report status blocked with one question of
> kind ambiguous. Do not say it only in `notes_for_verifier`. A step that lists a clause that no answer of this task
> settles is not kept: the harness asks about each listed clause and the step runs again with the answers. Where an
> answer of this task settles a clause, do what the answer says.

`contract.md` stays at 13: its blocked rule is the same rule for a contradiction, the field is a phase's concern, and a
bump would move the sixteen `contract@13` strings of the tests for no change of meaning. `output.md` stays at 1: the schema it prints
holds the field, and the phase sections say when to use it. The single-phase templates stay as they are (a fix chore
does what its finding decided); a single step that lists a new entry is still handled by D3. `templates.lock.json` is
regenerated with `uv run python -m l4.templatelock --write` (`tests/unit/test_template_lock.py` checks it), and the
template versions that tests and SPEC scenarios name move: `contract@13+red@14`, `contract@13+green@7`.

## Risks / Trade-offs

- **Over-reporting costs a wait.** Every new entry parks the unit until it is answered, and the step runs again. An agent
  that lists clauses it could have asserted makes the unit slower, never wrong; the rule asks it to assert what it can,
  and a task asks about a criterion once (D2). With the delegate on, the wait is one more run.
- **A weak delegate does not answer.** A delegate profile of a free model never answers an `ambiguous` question
  (L4-DLG-019), so such a project waits for a person, as for any ambiguous question today.
- **An agent can still write only a note.** The field is not a detector: a step that leaves a clause unasserted and
  lists nothing is judged as today. The rule in red and green and the contract's blocked rule are what make the agent
  use it; `l4 eval --compare` on the two templates measures whether they do.
- **A later clause of an asked criterion is not asked.** The judge gets it with the earlier answer's id; it may still
  need a verdict question. That is the price of a bounded loop.
- **A green whose code would pass is discarded when it lists a new entry.** Nothing of it is kept, as for any blocked
  green (its gates are not even run); the next green, with the answer, usually writes the same code with the answered
  value.
- **Up to six questions from one step** (three of its own, three entries). Each is a delegate call; `delegate.batch_size`
  batches verdict questions only, not these.
- **The questions of a `done` result stay unread.** An agent that puts a question there instead of in `unasserted` is
  not asked; this change leaves that as it is (D1 gives it the field to use).

## Not in this change

- Raising the `questions` of a `done` result (a separate decision: it would change what `status` means).
- A hold of verification by an open question whose task is done (D4, rejected).
- A change of the contract, the output section, the single-phase templates or the judge's system text (D6).
- A `verify.judge` field that counts the clauses shown: the published prompt holds them.
