## Why

In a consumer run, a red step wrote in its `notes_for_verifier` (recorded in `task.red_ok.notes`): "I did not assert
`entry.action`, because the spec text is ambiguous there". Nothing turned that sentence into a question. The green step
chose a value (`"continue"`), the judge passed the unit, and the next unit met another capability's spec, which says the
field is null. The answer arrived after the merge, and cost a verdict question and a spec fix.

What the harness has today does not catch it:

- The contract (`contract.md`, version 13) already says: when criteria contradict each other or existing behaviour,
  change nothing and report status `blocked` with one question of kind `ambiguous`. The agent wrote a note instead.
- A result's `questions` are raised only when its status is `blocked` (`tdd.agent_step`, `loop._raise_blocked`): the
  questions of a `done` result are dropped without a trace.
- The judge sees the notes: `ladder._notes` joins the `task.red_ok` and `task.done` notes (at most `MAX_NOTES_CHARS`,
  6,000) into the `notes_for_verifier` data block, headed `Hint from the implementer (UNVERIFIED: it may be wrong or
  self-serving; check it against the diff)`. It passed anyway: the one sentence that mattered was a hint to doubt at the
  end of the prompt, not a clause to check.
- An open question whose blocking task is done holds nothing: `questions.holds` counts pending tasks only, so the
  delegate (`due.held_ids`), the planner and the orchestrator ignore it, and the unit reaches verification and merges.

Reading the words of a note (`ambiguous`, `unclear`) is not a fix: it cannot be tested in the negative and it misfires
on prose. The agent needs a structured place to say "this clause is not asserted", and the harness a rule for it.

## What Changes

- The result object (`l4/implementer-result@1`) gains the optional list `unasserted`: at most 3 entries, each
  `{criterion, clause, why}` (a criterion id; the clause of its scenario, quoted, at most 300 characters; why, at most
  300 characters). The file-result schema keeps it; the strict copy for Codex makes it nullable; the normalization
  drops a malformed entry and cuts what is over a limit.
- An entry is *settled* when an answered question that the harness raised for the same task, fix unit and criterion
  exists (`question.raised{clause: {criterion, phase}}`); every other entry is *new*.
- A step of any phase that lists a new entry is handled as a `blocked` step, whatever its status: nothing of it is kept,
  it is not a failed attempt, and each new entry becomes one question of kind `ambiguous` that holds the task, whose
  title names the task, the phase and the criterion and whose context quotes the clause and the reason. The task stays
  pending, so the unit goes to the clarifier or `awaiting_human` and cannot reach verification while the question is
  open; the delegate answers it where it is in scope; the next step of the task reads the answer.
- A step whose entries are all settled is judged as today, and records them in `task.red_ok` / `task.done` as
  `unasserted: [{criterion, clause, why, question}]`.
- Every judge prompt carries those entries as a labelled list of clauses to check against the code, in its user text
  between the answers and the implementer's hint, separate from the notes; the judge's system text stays `judge@13`.
- `red.md` (version 14) and `green.md` (version 7) say when to fill the field; `templates.lock.json` is regenerated.

## Impact

- Code: `l4.implementer.result` (`Unasserted`, `ImplementerResult.unasserted`), the packaged schema and its fixture,
  `l4.implementer.normalize` (`_unasserted`), a new `l4.implementer.clauses` (`split_clauses`, `clause_question`),
  `l4.implementer.tdd` (`StepOutcome`, `RedOutcome`, `GreenOutcome` carry the new entries; `agent_step` turns a step
  with a new entry into `blocked`; the `task.red_ok` and `task.done` events record the settled ones),
  `l4.implementer.loop` (`_questions`, `_raise_blocked`), `l4.verifier.judge` (`ClauseRef`, `build_judge_prompt(clauses=)`),
  `l4.verifier.ladder` (`_clauses`, the judge budget), the templates `red.md` and `green.md`, `templates.lock.json`.
- Spec: L4-IMP-095 (new); amendments of L4-IMP-005 (the schema) and L4-IMP-020 (the normalization rule); SCN-IMP-510..519;
  the template versions named in SCN-IMP-280 and SCN-VER-170; change-table row 123. The runbook's `awaiting_human`
  procedure.
- Behaviour: a red or green step that says it leaves a clause unasserted is not committed; its clause is asked, the unit
  waits for the answer (a person's, or the delegate's where it is in scope) and the step runs again with it. A clause
  asked once for a task and criterion is not asked again; the judge checks it against the code.
- Not changed: the notes and their block; the meaning of `status`; the questions of a `done` result (still not raised);
  `contract.md`, `output.md`, the single-phase templates and the judge's system text; what holds a task (L4-QMD-005); the
  clarifier's routing (L4-CLR-002), the delegate's kinds and its scope.
