## 1. The field and its schema (D1)

- [ ] 1.1 Write the tests first. `tests/unit/implementer/test_result.py`: a result with `unasserted: [{criterion:
  "C-1a2b3c4d", clause: "its action is recorded", why: "the spec does not say"}]` parses into
  `result.unasserted[0].criterion == "C-1a2b3c4d"`; a minimal result has `unasserted == []`; `"unasserted": None` reads
  as absent; schema violations name the path for four items (`unasserted`), a missing `why` (`unasserted[0]`), a
  criterion `C-XYZ` and a clause of 301 characters. `tests/unit/implementer/test_normalize_contract.py`: the file schema
  keeps `unasserted` exactly as the canonical schema has it. `tests/unit/agents/test_codex.py` (SCN-IMP-517): change
  `test_strictified_canonical_schema_equals_the_recorded_strict_schema` to compare the recorded strict schema with
  `strictify_schema(CANONICAL)` less `unasserted` (from `properties` and from `required`), and assert that the strict
  `unasserted` is `{"type": ["array", "null"], "maxItems": 3, "items": {... "additionalProperties": false, "required":
  ["criterion", "clause", "why"]}, "description": ...}`; do NOT edit the recorded files under
  `tests/fixtures/recorded/codex/0.160.0/` (they are what that version was given and replied); the round-trip test
  stays as it is.
- [ ] 1.2 Then add the property of design D1 (after `questions`, with its `description`) to
  `src/l4/implementer/implementer-result.schema.json` and to `tests/fixtures/schemas/implementer-result.schema.json`
  (they must stay equal: `test_the_packaged_schema_is_the_canonical_copy`), and `Unasserted(_Open)` with
  `ImplementerResult.unasserted: list[Unasserted] = Field(default_factory=list)` to `src/l4/implementer/result.py`.
  Run `uv run --frozen pytest tests/unit/implementer/test_result.py tests/unit/implementer/test_normalize_contract.py
  tests/unit/agents/test_codex.py tests/contract/agents/test_opencode_replay.py -q`.

## 2. The normalization rule (D1)

- [ ] 2.1 Write the tests first in `tests/unit/implementer/test_normalize.py` (SCN-IMP-514): an `unasserted` that is a
  string is dropped (`{field: "unasserted", fix: "dropped"}`); items without `why`, with `criterion: "C-XYZ"`, with a
  non-string `clause`, or that are not objects are dropped with one `count`; four well-formed items keep three
  (`{field: "unasserted", fix: "cut", count: 1}`); a clause of 400 and a why of 350 characters keep their start and end
  with `CUT_MARKER` within 300 (`{field: "unasserted.clause", fix: "cut", length: 400}`, the same for `why`); a
  well-formed list gives no fix; the normalized object still passes `parse_result`. Then add `_unasserted` to
  `src/l4/implementer/normalize.py`, called from `normalize` after `_drops` and before `_cuts` (or folded into them),
  with the limits read from `_PROPS["unasserted"]` as the other limits are. Run `tests/unit/implementer/test_normalize.py`
  and `tests/unit/implementer/test_normalize_find.py`.

## 3. New and settled entries, and the question of each (D2, D3)

- [ ] 3.1 Write the tests first (`tests/unit/implementer/test_unasserted_clauses.py`, new), with `make_bench` and the
  `result(...)` helper of `tests/unit/implementer/conftest.py`: `clauses.split_clauses(wb, task, entries)` gives `new`
  for an entry with no earlier question; `settled` with the question id when a `question.raised{task: "1.1", clause:
  {criterion, phase: "red"}}` is in the ledger and `questions.md` has that question `answered` (also `accepted`,
  `dismissed`); `new` when that question is `open`, when the `question.raised` is of another task, of another criterion,
  or of a fix unit when the step is the unit's own (and the reverse); the newest of two answered questions settles.
  `clauses.clause_question(task, phase, entry, criteria)` gives kind `ambiguous`, the title `Task 1.1 (red) left a clause
  of C-1a2b3c4d unasserted: its action is recorded`, the context of design D3 (the quote, `Its reason: …`, `The step was
  not kept.`), `criteria` with the criterion when it is the unit's, and the sentence `C-99999999 is not one of this
  unit's criteria.` and no criterion when it is not.
- [ ] 3.2 Then add `src/l4/implementer/clauses.py` (new): `Split(new: tuple[Unasserted, ...], settled:
  tuple[tuple[Unasserted, str], ...])`, `split_clauses(wb, task, entries) -> Split` (reads `_answer_events(wb)` and
  `QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)`; the key is task, `fix_unit` and criterion, never the clause's
  text), `ClauseAsk(question: ResultQuestion, criterion: str, known: Criterion | None)` and `clause_question(...) ->
  ClauseAsk`. Do not add a field to `ResultQuestion` (the agent's schema model): the marker of a clause question is the
  harness's. Run the new file.

## 4. A step with a new entry is a blocked step (D3, D4)

- [ ] 4.1 Write the tests first, in `tests/unit/implementer/test_unasserted_clauses.py`, through `run_task` with
  `make_bench` (as `test_blocked_result_writes_question_and_stops` in `tests/unit/implementer/test_loop.py` does):
  SCN-IMP-510 (a red step that writes a failing test and reports `done` with one entry: `outcome.status == "blocked"`,
  no `test(` commit, only the questions commit, `[ ] 1.1` still in `tasks.md`, no `task.attempt_failed`, the question's
  title, `- **Kind:** ambiguous`, `- **Blocking tasks:** 1.1`, `- **Criteria:** C-…`, the quoted clause and reason in its
  context, `question.raised` with `clause == {"criterion": …, "phase": "red"}`, one agent call); SCN-IMP-511 (the
  question answered, the next `run_task`: the red prompt holds the answer block; a red step that lists the same
  criterion again with other words is committed, its `task.red_ok.unasserted` is `[{criterion, clause, why, question:
  "Q-001"}]`, no second question); SCN-IMP-512 (a committed red, then a green that reports `done` with one entry: the
  worktree is back at the red commit, no `feat(` commit, `[ ] 1.1`, one green clause question; after the answer the
  task resumes at green (`task.red_resumed`) and the green prompt holds the answer); SCN-IMP-515 (a red whose
  `notes_for_verifier` holds `I did not assert entry.action, because the spec text is ambiguous there` and no
  `unasserted`: committed, no question, `task.red_ok.notes` holds the sentence); SCN-IMP-519 (a `blocked` red with one
  question of its own and one new entry: `Q-001` is its own, `Q-002` the clause's, no `Task 1.1 is blocked`; a single
  step of a fix unit's chore with a new entry: the question is in the fix unit's `questions.md` and its
  `question.raised` has `fix_unit`); a three-entry step raises three questions in order; a step with one settled and
  one new entry is blocked and asks only the new one.
- [ ] 4.2 Then change `src/l4/implementer/tdd.py`: `StepOutcome`, `RedOutcome` and `GreenOutcome` gain `clauses:
  tuple[ClauseAsk, ...] = ()`; in `agent_step`, after `parse_result`, `split = split_clauses(wb, task,
  result.unasserted)`, and `if result.status == "blocked" or split.new:` return `StepOutcome("blocked", result,
  dropped_questions=..., clauses=tuple(clause_question(task, role, e, criteria) for e in split.new))`; `_red_exit` and
  the `blocked` exits of `run_green`, `run_single` and `_run_repair` pass `clauses` on. Change
  `src/l4/implementer/loop.py`: `_questions(..., clauses=())` appends the clause questions after the result's own (as
  `NewQuestion` with `criteria=(known,)` when known) and makes the summary question only when there is neither;
  `_raise_blocked(..., clauses=())` records `clause={"criterion": ask.criterion, "phase": <phase>}` on each clause
  question's `question.raised`; `_run_task` passes `outcome.clauses` / `done.clauses` in its three `blocked` branches.
  `_suggest_edits` is unchanged (a clause question is not technical). Run the new file, `tests/unit/implementer/test_loop.py`,
  `tests/unit/implementer/test_tdd_red.py`, `tests/unit/implementer/test_tdd_green.py`,
  `tests/unit/implementer/test_single_phase.py` and `tests/unit/implementer/test_question_asker.py`.
- [ ] 4.3 Write the orchestrator test first (`tests/unit/orchestrator/test_unasserted_clause.py`, new, with `run_l4`
  as `tests/unit/orchestrator/test_reentry.py` uses it): SCN-IMP-513 (a unit of one task whose red lists a new entry: the
  run exits 11 in `awaiting_human`; a second run with the question still open runs no agent step and records no
  `verify.*` event; after `l4 questions answer` the next run resumes the task). Today a blocked task parks the unit at
  once, before any other task, and that stays. Nothing in the orchestrator should need to change; if it does, stop and
  report.

## 5. Settled entries are recorded, and the judge checks them (D5)

- [ ] 5.1 Write the tests first, in `tests/unit/implementer/test_unasserted_clauses.py`: the `task.red_ok` of a red
  commit and of an already-satisfied commit, the `task.done` of green and the `task.done{tdd: "exempt"}` of a single step
  carry `unasserted` with the settled entries (texts redacted: a clause holding a value the redactor knows is written
  redacted); no `unasserted` key when there are none; the already-satisfied `task.done` and an accepted repair's
  `task.done` carry none. Then write them in `run_red` (both `task.red_ok` emits), `run_green` (its `task.done`) and
  `run_single` (its `task.done` at the end), each from `split_clauses(wb, task, result.unasserted).settled` (an entry no
  longer settled is written without `question`).
- [ ] 5.2 Write the tests first in `tests/unit/verifier/test_judge_clauses.py` (new), beside
  `tests/unit/verifier/test_judge_answers.py` (SCN-IMP-516): `build_judge_prompt(clauses=[ClauseRef(...)])` has the
  section heading of design D5, its instruction (`A passing test does not show a clause listed here`), the line
  `C-1a2b3c4d  task 1.1 (red): "its action is recorded" | why: the spec does not say | answer: Q-001` inside `<l4:data
  source="unasserted clauses">`, placed after the answers section and before `## Hint from the implementer`; the hint
  block is unchanged; a prompt whose `criteria` lack the entry's criterion has no line, and with no line no section;
  without `clauses` the user text is byte for byte today's (compare with a prompt built without the keyword); a
  closing `</l4:data>` inside a clause cannot end the block (`defuse`); lines past 6,000 characters are counted in
  `(+N clauses not shown)`; `prompt.system is SYSTEM` and the version is `judge@13`. `ladder._clauses(events)` reads
  `task.red_ok` (phase `red`), `task.done` (phase `green`) and `task.done{tdd: "exempt"}` (phase `single`) in ledger
  order, and skips malformed records. Then add `ClauseRef`, `MAX_CLAUSES_CHARS` and the `clauses` keyword (with the
  section built inside `build_judge_prompt`, filtered by `criteria`) to `src/l4/verifier/judge.py`, and to
  `src/l4/verifier/ladder.py` `_clauses` and `"clauses": _clauses(events)` in `prompt_for`, with the block's length
  added to `plan_context(fixed_chars=...)`. Run the new file, `tests/unit/verifier/test_judge_answers.py`,
  `tests/unit/verifier/test_judge_followup_prompt.py`, `tests/unit/verifier/test_judge_length_split.py` and
  `tests/unit/verifier/test_prompt.py`.

## 6. The templates (D6)

- [ ] 6.1 Write the tests first (SCN-IMP-518), in `tests/unit/implementer/test_prompt.py`: the rendered red prompt holds
  `list it in \`unasserted\``, `for any reason` and `is not kept`; the green prompt holds `do not choose it: list it in
  \`unasserted\`` and `is not kept`; then move the version assertions: `contract@13+red@14` (test_prompt.py,
  test_prompt_context.py, test_prompt_output.py with `+output@1`), `contract@13+green@7` (test_prompt.py,
  test_suggested_edit.py, and `template.version == 7` there), `load_template("red").version == 14`
  (test_check_criteria.py). Then add the two paragraphs of design D6 word for word to
  `src/l4/implementer/templates/red.md` (after `Leave every other existing test as it is: …`) and
  `src/l4/implementer/templates/green.md` (after the binding-decision rule), set `version: 14` and `version: 7`, and
  regenerate the lock with `uv run --frozen python -m l4.templatelock --write`. `contract.md`, `output.md` and the single
  templates do not change. Run `tests/unit/test_template_lock.py`, `tests/unit/implementer/test_prompt.py`,
  `tests/unit/implementer/test_prompt_context.py`, `tests/unit/implementer/test_prompt_output.py`,
  `tests/unit/implementer/test_suggested_edit.py` and `tests/unit/implementer/test_check_criteria.py`.

## 7. Docs and checks

- [ ] 7.1 `docs/runbook.md` §7.1 (`awaiting_human`): one paragraph on a question titled `Task <k> (<phase>) left a clause
  of <criterion> unasserted: …` (the step listed the clause in `unasserted` and was not kept; answer with what the clause
  means, or that it stays unasserted; the next step reads the answer; the task asks about a criterion once). SPEC.md and
  CHANGELOG.md were written with this spec: check every name and text they quote against the code (the title, the
  context sentences, the section heading, the line format, `clause: {criterion, phase}`, the fix names) and fix any
  drift in both.
- [ ] 7.2 Run `python3 scripts/check_spec.py docs/SPEC.md`, `uv run --frozen pytest tests/unit/docs -q`, `uv run
  --frozen pytest tests/unit/implementer -q`, `uv run --frozen pytest tests/unit/verifier -q -k "judge or prompt"`,
  `tests/unit/agents/test_codex.py`, `tests/unit/test_template_lock.py`, the new orchestrator test, `uv run --frozen ruff
  check src tests`, `uv run --frozen ruff format --check src tests` and `openspec validate unasserted-clause-question
  --strict`. Do not run the whole suite more than once, never two at a time, and never wait on a process with a
  `while pgrep` loop.
