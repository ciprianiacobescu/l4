## Why

In a consumer unit a new browser test failed at verification step 3 by assertion (`assert 1508 == 1500`: a page built
with `page.set_content` kept the browser's default body margin). The verifier spawned a fix unit. Its chore's
implementer could not change the test or the support file the test uses, so the guard put back its edit and it asked a
question; the delegate escalated the question to a person. Neither the fix task nor the question carried the failure
message, so the implementer wrote that it "did not reproduce" the failure and nobody saw the one-line cause.

What exists at 0.4.58 (verified in code):

- The round's `verdict.json` holds `failures` (L4-VER-069): per failing test `{gate, kind, message}`, where `message`
  is the FIRST line of the failure message, redacted, at most 200 characters (`verifier/gates.py` `failure_records`),
  plus `location` and `frames`. That file is committed to the unit branch, so the first line was on the branch; it never
  travelled further. The traceback lines after it (for a Playwright `expect`, the expected and received values) are
  recorded nowhere.
- The fix proposal (`specs/openspec.py` `_proposal`, Kiro `specs/kiro.py` `_fix_design`) is built from `Finding.detail`.
  For `e2e gate failed` that is `` `<command>` failed: exit code 1; failing: <ids> `` (`verifier/gates.py` `_judged`);
  for `new tests failed` the ids. `plan_fix_unit` cuts a chore's detail at 600 characters. Only a repair task
  (L4-IMP-091) gets the messages and the end of the gate log (`fixunit._repair_detail`).
- The fix chore's prompt (`implementer/prompt.py`) gets the task title, the unit context (the fix unit's
  `proposal.md`, which the context planner cuts first) and, on a retry, the previous failure. A fix chore for an e2e
  finding that runs the e2e gate (L4-IMP-090) puts the failure excerpt into that previous failure, but a first attempt
  that asks a question has none.
- A question's Context (`implementer/loop.py` `_questions`, `_with_note`) is the agent's text and a harness note on
  unfreezing; nothing of the round's failures and nothing of the task's last failed attempt. The ledger's
  `task.attempt_failed` holds a bounded excerpt (L4-IMP-064), but only for an attempt that failed.

## What Changes

- Step 3 records, for each of the first 20 failing tests of each gate, an `excerpt` in its `failures` record: the lines
  the retry prompt shows for that test (the `E` lines, the deepest repository frame), paths relative to the worktree,
  redacted before and after it is cut, at most 8 lines and 600 characters. A module that did not collect gets the `E`
  lines of its collection error the same way.
- A fix task whose findings name failing tests carries a *failure block*: each test as `<id> (<kind>, <gate>):` with its
  excerpt (or its message), at most 8 tests and 6,000 characters, the rest counted. It goes into the fix unit's
  `proposal.md` (OpenSpec) or `design.md` (Kiro) as an indented block under the finding (six spaces in OpenSpec, where the finding is a list item; four in Kiro), never
  into `tasks.md`.
- The prompt of a fix chore (kind `fix`) holds the block as a data block that the context budget never cuts, read from
  the round that spawned the fix unit.
- A question raised by a fix chore gets the block as a harness note, and every question raised by an attempt that
  follows a failed attempt of the same task in the run gets that failure's reason (redacted before the 300-character cut
  and after) and its ledger excerpt. The notes are in their own `### Harness notes` subsection of the question, not in
  its Context, so that text from a test's output cannot widen what an accepted suggestion unfreezes (L4-IMP-015).
- A private-key block that reaches an excerpt with one marker only (a report keeps the last 4,000 characters of a body
  and the first 500 of a message) is removed to the edge of the text; a collection error's excerpt is cut at 8 lines
  like a test's.

Non-goals: the repair chore's prompt (it has its own `Tests to repair` block); the gate log itself; a test past the
20 excerpts of its gate (it keeps its `message`); `tasks.md` text.

## Capabilities

### New Capabilities

- `fix-failure-excerpt`: L4-VER-078 (the round records a bounded excerpt per failing test) and L4-IMP-102 (a fix task,
  its prompt and its questions carry it).

### Modified Capabilities

- L4-VER-069 keeps its keys; the record gains an optional `excerpt`, which readers that do not know it ignore.

## Impact

- `src/l4/implementer/excerpt.py` (`case_excerpt`, `collection_case_excerpt`), `src/l4/verifier/gates.py` (`failure_records`),
  `src/l4/verifier/ladder.py` (`tests()`), `src/l4/verifier/failures.py` (`failure_block`, `shown_failure_ids`),
  `src/l4/verifier/fixunit.py` (`plan_fix_unit`, `redact_plan`), `src/l4/specs/base.py` (`Finding.failures`), `src/l4/specs/questions.py` (`NewQuestion.notes`, the `### Harness notes` subsection, `Question.notes_text`), `src/l4/clarifier/ports.py`,
  `src/l4/specs/openspec.py` (`_proposal`), `src/l4/specs/kiro.py` (`_fix_design`), `src/l4/implementer/prompt.py`
  (`PromptContext.failing_tests`), `src/l4/implementer/tdd.py` (`run_single`, `step_or_replay`, `agent_step`,
  `_prompt`), `src/l4/implementer/loop.py` (`_raise_blocked`, `_questions`, `_run_task`).
- `docs/SPEC.md` (L4-VER-078, L4-IMP-102, SCN-VER-308..310, SCN-IMP-557..561, change-table row 134), `CHANGELOG.md`.
- `verdict.json` grows by at most 2 x 20 x 600 characters of excerpt (the keys, ids and JSON around them are not counted); no new ledger event; no configuration key.
