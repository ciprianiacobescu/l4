## Context

Read at 0.4.58 (f0bc8a3c):

- `verifier/gates.py` `failure_records(unit, browser, redact)` builds the `failures` map of L4-VER-069 from the two
  step-3 reports; `_first_line` keeps the first non-empty line of `case.message`, redacted, cut at
  `MAX_FAILURE_CHARS` (200); `location`/`frames` come from `case.detail`. `ladder.tests()` (~804) calls it with
  `wb.redactor.redact_text`; `verdict_json` writes the map, `write_round_evidence` redacts the whole object again
  (`redact_obj`) and scrubs it for the commit; `evidence.restore_round` copies every key of every record.
- `implementer/excerpt.py` `failure_excerpt(report, ids, worktree, tmp_root, redact)`: per test the `E` lines (at most
  6), the deepest repository frame's `>` line and location and the last location (`_test_lines`, at most 8 lines), the
  body redacted whole before a line is dropped, paths made relative (`_clean`), the result redacted again; 40 lines and
  3,000 characters in all. The retry prompt's excerpt.
- `verifier/fixunit.py` `plan_fix_unit` -> `Finding(ids, title, detail, ...)` per task; a chore's detail is
  `_fit_detail(cand.detail, ..., 600)`; `redact_plan` redacts `title`, `detail`, `request`, `code` by name.
  `specs/openspec.py` `_proposal` writes each finding as one `_plain` line (cut at 5,000 characters, whitespace folded);
  `specs/kiro.py` `_fix_design` writes `_line(finding.detail, MAX_ITEM_CHARS)` and `finding.code` as an indented block.
- `implementer/tdd.py` `_parent_verdict(wb)` reads the verdict of the round that spawned this fix unit
  (`fix.spawned.verify_round`, from the parent's folder); `run_single` uses it for the e2e duty (L4-IMP-090).
- `implementer/loop.py` `_raise_blocked(wb, task, questions, summary, step, red, chore_unit, clauses, phase)` ->
  `_questions(...)` builds each `NewQuestion.context` with `_with_note` (the forbidden-path note, the fix chore's note
  `chore_question_note`, or green's unfreeze note); `raise_questions` redacts the Context (`_clean`) and escapes
  structural lines (`_block`). `_run_task` keeps `failure` and `excerpt` of the last failed attempt of the phase
  (`red, failure, retry, excerpt = outcome, None, None, ""` when red commits), and `_ledger_text(wb, excerpt)` is the
  bounded form the ledger keeps.

## Goals / Non-Goals

**Goals:** the failure text of each test a fix task is about reaches the fix proposal, the fix chore's prompt and any
question the fix chore raises; a question raised after a failed attempt shows why that attempt failed. Every piece is
bounded and redacted.

**Non-Goals:** the gate log; the repair chore's prompt; `tasks.md`; excerpts past 20 per gate; a new event or key.

## Decisions

### D1. What step 3 records

`case_excerpt(case, *, worktree, tmp_root, redact, limit=MAX_RECORD_EXCERPT_CHARS) -> str` in
`l4.implementer.excerpt` (the name must not start with `test`: a test module that imports it would collect it): the
lines `failure_excerpt` keeps for one test (`_test_lines` of the redacted body, or the first 8 lines of the redacted
message when there is no body), empty lines dropped, `_clean` applied, redacted again, then cut at the last line end
before `limit` (a single line longer than `limit` is cut at `limit`); `""` when nothing is left. `MAX_RECORD_EXCERPT_CHARS
= 600`, the bound of the ledger's excerpt (`ledger_excerpt`, L4-IMP-064).

`failure_records(unit, browser, redact, *, excerpt=None, collection_excerpt=None)`: when `excerpt` is given, the first
`MAX_EXCERPT_RECORDS = 20` failed or errored tests of each gate in sorted id order get `"excerpt": excerpt(case)` when it
is not empty; a module that did not collect, among those 20 by its id, gets `collection_excerpt(detail)`
(`error_lines(detail, 600)` with `_clean` and the redactor). The other keys and the 200-record cap of the `test` side
are unchanged; the excerpt adds no record. `ladder.tests()` passes both, with `worktree=wb.worktree`, `tmp_root=wb.unit_cache
/ "gate-tmp"` and `redact=wb.redactor.redact_text`, as `tdd.excerpter` does.

Redaction: the body is redacted whole before any line is dropped (a private key cut in half would no longer match),
the excerpt is redacted again after it is assembled, and the verdict is redacted again when written. A cut after the
redaction can only drop text, never uncover it.

Size: at most 2 x 20 x 600 = 24,000 characters more in a `verdict.json`.

### D2. Which tests a fix task is about

`shown_failure_ids(failures, title, detail) -> list[str]` in `l4.verifier.failures` (plain data, no harness import): for
`test gate failed` / `e2e gate failed` every record of that gate (collection records included, sorted); for `new tests
failed` / `new tests errored` the recorded ids its detail names (`named_known_ids`, the part that matches, even when the
list was cut); for any other title none. A task's ids are the union over its findings, sorted, each once.

### D3. The failure block

`failure_block(failures, ids) -> str` in `l4.verifier.failures`: for each id, `<id> (<kind>, <gate>):` then each line of
its `excerpt`, or its `message` when it has none, indented by two spaces; at most `MAX_SHOWN_FAILURES = 8` tests and
`MAX_FAILURE_BLOCK_CHARS = 6000` characters, whole tests only, and a last line `and <n> more failing tests (the round's
verdict.json)` for the rest. `""` when no id has a record. It is plain text: whoever puts it in a file or a prompt fences
it (D4, D5, D6).

### D4. The fix unit's files

`Finding` (`l4.specs.base`) gains `failures: str = ""`. `plan_fix_unit` sets it for every task that is not a feedback
item, from `result.failures` and the findings the task groups (`_Candidate` keeps the ids of D2 per finding as it groups
them), the repair chore included. `redact_plan` redacts it with the other text fields.

- OpenSpec `_proposal`: right after a finding's line in `## What Changes`, when `f.failures` is set, a blank line, the
  line `    Failing tests as the verifier recorded them:` and the block with every line indented by four spaces (empty
  lines stay empty), as `_requests` writes quoted code. An indented line can neither open a heading, a list or a fence
  nor close one, and `openspec validate --strict` accepts it (checked with the OpenSpec CLI on a scratch change; the
  CLI counts checkboxes in `tasks.md` only).
- Kiro `_fix_design`: after the finding's detail, the same lead line and indented block (`finding.code`'s pattern).
- `tasks.md` is not touched: a task is one line there, and the OpenSpec CLI counts any line of `tasks.md` that looks
  like a checkbox, inside code fences too.

### D5. The fix chore's prompt

`PromptContext.failing_tests: str = ""` (single only). `render_prompt` adds, for role `single` when it is set and the
step is not a repair, after the previous-attempt block: `# Failures of this task's tests` and "The verifier recorded
these failures for the tests this task's findings name; paths are relative to the repository. They are what this task
must fix." followed by `data_block("failing tests", ctx.failing_tests)`. It is part of the text the context budget does not
govern (`after`), so `proposal.md` being cut does not lose it.

`run_single` (kind `fix`) computes it once before the step: `fix_failure_text(wb, findings)` = `failure_block` of the
ids of D2 for the stored findings of `_parent_verdict(wb)` whose id is in `findings`; `""` with no verdict (a recovered
fix unit, an older harness). It is passed through `step_or_replay(..., failing=...)` and `agent_step(..., failing=...)`
to `_prompt(..., failing=...)`.

### D6. The questions

`_questions` gains `notes: Sequence[str] = ()`: each note goes into every question's Context after the agent's own text
and BEFORE the harness note that `_with_note` adds (a blank line between each), the question made from a bare blocked
summary and the clause questions included. The harness note stays last because SCN-IMP-398 pins that a fix chore's
question ends with the fix-task note, and green's unfreeze note keeps its place too; the delegate finds a chore's
question by `chore: true` and by the note's first sentence, which does not change. `_raise_blocked` gains the same
keyword. In `_run_task`:

- the chore branch passes, when `fix_failure_text(wb, chore)` is not empty, `"Harness note: the verifier recorded these
  failures for the tests of this task's findings:\n" + block`;
- every branch (red, green, single) passes, when `failure` is set (an earlier attempt of the phase failed in this run),
  `f"Harness note: the previous attempt of this task was rejected: {failure[:300]}"` followed, when `excerpt` is set, by
  a new line and `_ledger_text(wb, excerpt)` (600 characters, redacted).

The question of a hung frozen test (`_hang_question`) is about the attempt that just failed and gets neither. A held
check's question (`_raise_held`) is unchanged. `raise_questions` redacts and escapes the Context as before.

### D7. Where the text ends up

`verdict.json`, the fix unit's files and `questions.md` are committed and pushed, and on a public forge they are
public. The excerpt holds no more than the retry prompt and the committed ledger already hold for an attempt, and it is
redacted three times (D1). Paths are relative to the worktree and the gate's tmp root is `<tmp>`.

### D8. Older verdicts

A record without `excerpt` shows its `message`; a verdict without `failures` gives an empty block, and nothing is
added anywhere. Readers of `failures` that do not know the key (`repairs`, `fixunit._joined_to_gate`, `e2e_ids_of`)
ignore it.

## Risks / Trade-offs

- A secret shape the redactor does not know is now copied into three more files. The same text already reaches the
  retry prompt and the committed ledger excerpt.
- An excerpt can mislead when the first `E` lines are a library's and the real cause is lower; the bound is that of the
  retry prompt, which has served the implementer since L4-IMP-064.
- The 20-per-gate cap leaves a large failing round's later tests with their first line only.
